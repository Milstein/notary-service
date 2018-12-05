import uuid
import networkx as nx
import tempfile
import os
from neo4j import GraphDatabase
import neo4j
from typing import List, Set, Dict, Tuple, Optional
from .abstract_workflow import AbstractWorkflow, WorkflowException
import json
import time
import logging
import sys


class Neo4jWorkflow(AbstractWorkflow):

    def __init__(self, url: str, user: str, pswd: str, importHostDir: str = None, importDir: str = None) -> None:
        """ URL of Neo4j instance, credentials and directory
        from where Neo4j can import graphs"""
        self.url = url
        self.user = user
        self.pswd = pswd
        self.importHostDir = importHostDir
        self.importDir = importDir
        self.driver = GraphDatabase.driver(self.url, auth=(user, pswd))

        self.log = logging.getLogger(__name__)

    def _prep_workflow(self, graphml: str, graphId: str = None) -> Tuple[str, str, str]:
        """Import a workflow graphml, assigning it a new unique graph ID
        return the name of the file where graph is saved with updated GraphID
        and the assigned graphID"""
        if graphId is None:
            graphId = str(uuid.uuid4())

        # save to file
        f1 = tempfile.NamedTemporaryFile(suffix="-graphml", mode='w')
        f1.write(graphml)

        # read using networkx
        g = nx.read_graphml(f1.name)
        f1.close()

        for n in list(g.nodes):
            g.nodes[n]['GraphID'] = graphId

        # save back to GraphML
        # where to save is determined by whether importDir is set
        destDir = self.importHostDir
        if self.importHostDir is None:
            destDir = tempfile.gettempdir()

        uniqName = str(uuid.uuid4())
        hostFileName = os.path.join(destDir, uniqName)
        mappedFileName = os.path.join(self.importDir, uniqName)
        nx.write_graphml(g, hostFileName)

        return graphId, hostFileName, mappedFileName

    def _import_workflow(self, graphmlFile: str) -> None:
        """ import graph into Neo4j from a file"""

        with self.driver.session() as session:
            session.run('call apoc.import.graphml( $fileName, {batchSize: 10000, readLabels: true, storeNodeIds: true, defaultRelationshipType: "isPrerequisiteFor" } ) ',
            fileName=graphmlFile)

    def import_workflow(self, graphml: str, graphId: str = None) -> str:
        """ import graph into Neo4j from a string, assigning it a unique id"""

        id, hostFileName, mappedFileName = self._prep_workflow(graphml, graphId)
        self.log.debug('Importing workflow with id %s for id %s', id, graphId)

        if graphId is not None:
            assert (id == graphId)

        retry = 5
        while retry > 0:
            try:
                self._import_workflow(mappedFileName)
                retry = - 1
            except neo4j.exceptions.ClientError as neo4jerr:
                self.log.error("Unable to load, deleting graph %s", id)
                self.delete_workflow(id)
                retry = retry - 1
                time.sleep(1.0)

        # remove the file
        os.unlink(hostFileName)

        if retry == 0:
            raise(WorkflowException('Unable to load graph'))

        return id

    def _validate_workflow(self, graphId: str, rulesFile: str) -> None:
        """ validate the graph imported in Neo4j according to a set of given Cipher rules"""
        f = open(rulesFile)
        rulesDict = json.load(f)
        f.close()

        for r in rulesDict:
            with self.driver.session() as session:
                #print('Applying rule ', r['msg'])
                v = session.run(r['rule'], graphId=graphId).single().value()
                #print("Rule {}, value {}".format(r['msg'], v))
                if v is False:
                    raise WorkflowException(r['msg'])

        return True

    def validate_workflow(self, graphId: str) -> None:
        """ validate the graph imported in Neo4j according to standard Cipher rules """

        self.log.debug('Validating workflow %s', graphId)
        return self._validate_workflow(graphId, os.path.dirname(__file__) + '/rules.json')

    def delete_workflow(self, graphId: str) -> None:
        """ delete a workflow with this ID from Neo4j"""
        self.log.debug('Deleting workflow %s', graphId)
        with self.driver.session() as session:
            session.run('match (n {GraphID: $graphId })detach delete n', graphId=graphId)

    def count_nodes(self, graphId: str, nodeRole: str = None) -> int:
        """ count the nodes of particular role in workflow"""
        self.log.debug('Counting nodes in graph %s', graphId)
        with self.driver.session() as session:
            if nodeRole is None:
                return session.run('match (n {GraphID: $graphId }) return count(n)',
                                   graphId=graphId).single().value()
            else:
                return session.run('match (n {GraphID: $graphId, Role: $nodeRole} ) return count(n)',
                                   graphId=graphId, nodeRole=nodeRole).single().value()
