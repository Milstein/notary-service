"""
SAFE post assertions
"""

# mock SAFE calls

import base64
import binascii
import hashlib


def mock_get_id_from_pub(public_key):
    """
    getIdFromPub("$KD/strong-1.pub")
    as WP, DSO, NSV
    :param public_key:
    :return:
    """
    with open(public_key, 'r') as pubkey:
        data = pubkey.read()
    data = bytes(data, 'ascii')
    digest = hashlib.sha256(binascii.a2b_base64(data)).digest()
    encoded = base64.b64encode(digest).rstrip(b'=')
    return encoded.decode('utf-8')


# end mock SAFE calls


def get_id_from_pub(public_key):
    """
    getIdFromPub("$KD/strong-1.pub")
    as WP, DSO, NSV
    :param public_key:
    :return:
    """
    pass


def post_raw_idset(principal):
    """
    ostRawIdSet("strong-2")
    as WP, DSO, NSV
    :param principal:
    :return:
    """
    pass


def post_per_flow_rule(workflow):
    """
    postPerFlowRule($WF1)
    :param workflow:
    :return:
    """
    pass


def post_two_flow_data_owner_policy(dataset, workflow_1, workflow_2):
    """
    postTwoFlowDataOwnerPolicy($DataSet, $WF1, $WF2)
    as DSO
    :param dataset:
    :param workflow_1:
    :param workflow_2:
    :return:
    """
    pass


def post_common_completion_receipt(project, workflow):
    """
    postCommonCompletionReceipt("someProject", $WF1)
    as NSV
    :param project:
    :param workflow:
    :return:
    """
    pass


def post_user_completion_receipt(user, project, workflow):
    """
    postUserCompletionReceipt("someUser", "someProject", $WF1)
    as NSV
    :param user:
    :param project:
    :param workflow:
    :return:
    """
    pass


def post_link_receipt_for_dataset(user, project, dataset, workflow):
    """
    postLinkReceiptForDataset("someUser", "someProject", $DataSet, $WF1)
    as NSV
    :param user:
    :param project:
    :param dataset:
    :param workflow:
    :return:
    """
    pass
