from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone

from comanage.ldap import get_comanage_project_names
from datasets.models import Dataset, NSTemplate
from infrastructure.models import Infrastructure
from users.models import Affiliation
from users.models import NotaryServiceUser
from workflows import views as wf_views
from workflows.models import WorkflowNeo4j
from workflows.workflow_neo4j import delete_workflow_by_uuid
from .forms import ProjectForm
from .models import Project, ComanageStaff, ComanagePIAdmin, ComanagePIMember, MembershipAffiliations, \
    MembershipComanageStaff, MembershipComanagePIAdmin, MembershipComanagePersonnel, MembershipComanagePIMember, \
    MembershipDatasets, MembershipProjectWorkflow, \
    MembershipInfrastructure, ComanagePersonnel
from .projects import update_comanage_group, personnel_by_comanage_group, update_comanage_personnel, \
    create_new_project, update_project_personnel, update_project_affiliations
from .workflows import create_base_project_workflows, generate_neo4j_user_workflow_status


def projects(request):
    context = {"projects_page": "active"}
    if request.user.is_authenticated:
        if request.POST.get("check-comanage-projects"):
            local_projects = Project.objects.values_list('comanage_name', flat=True).distinct()
            comanage_projects = get_comanage_project_names()
            for project in comanage_projects:
                if project not in local_projects:
                    create_new_project(project)
        return project_list(request)
    else:
        return render(request, 'projects.html', context)


def project_validate(ds_objs, show_uuid, project_uuid, user):
    for ds in ds_objs:
        if not ds.is_valid:
            if show_uuid:
                return False, 'Dataset ' + str(ds.uuid) + ' is not validated'
            else:
                return False, 'Dataset (' + str(ds.description)[:34] + '..) is not validated'
    create_base_project_workflows(project_uuid, user)
    return True, None


def project_detail(request, uuid):
    project = get_object_or_404(Project, uuid=uuid)
    update_project_personnel(project_obj=project)
    update_project_affiliations(project_obj=project, user=request.user)
    if request.method == "POST":
        if request.POST.get("refresh-personnel"):
            update_comanage_group()
            update_comanage_personnel()
            for group_pk in MembershipComanageStaff.objects.values_list('comanage_group_id').filter(
                    project=project.id
            ):
                if not MembershipComanageStaff.objects.filter(
                        project=project.id,
                        comanage_group=group_pk
                ).exists():
                    MembershipComanageStaff.objects.create(
                        project=project,
                        comanage_group=ComanageStaff.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanageStaff.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=None,
                                comanage_pi_members=None,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk)
                            )
    affiliations = MembershipAffiliations.objects.values_list('affiliation__uuid', flat=True).filter(
        project__uuid=project.uuid,
    )
    comanage_pi_admins = ComanagePIAdmin.objects.filter(
        cn__contains='-PI:admins',
        project=project
    ).order_by('cn')
    comanage_pi_members = ComanagePIMember.objects.filter(
        cn__contains='-PI:members:active',
        project=project
    ).order_by('cn')
    comanage_staff = ComanageStaff.objects.filter(
        cn__contains='-STAFF:members:active',
        project=project
    ).order_by('cn')
    project_pi_admins = list(MembershipComanagePersonnel.objects.values_list(
        'comanage_pi_admins__cn',
        'person__cn',
        'person__employee_number',
        'person__eppn',
        'person__email',
        'person__uid',
    ).order_by(
        'person__cn',
        'comanage_pi_admins__cn',
    ).filter(
        project=project,
        comanage_pi_admins__in=comanage_pi_admins
    ))
    project_pi_members = list(MembershipComanagePersonnel.objects.values_list(
        'comanage_pi_members__cn',
        'person__cn',
        'person__employee_number',
        'person__eppn',
        'person__email',
        'person__uid',
    ).order_by(
        'person__cn',
        'comanage_pi_members__cn',
    ).filter(
        project=project,
        comanage_pi_members__in=comanage_pi_members
    ))
    project_staff = list(MembershipComanagePersonnel.objects.values_list(
        'comanage_staff__cn',
        'person__cn',
        'person__employee_number',
        'person__eppn',
        'person__email',
        'person__uid',
    ).order_by(
        'person__cn',
        'comanage_staff__cn',
    ).filter(
        project=project,
        comanage_staff__in=comanage_staff
    ))
    ds_list = MembershipDatasets.objects.values_list('dataset__uuid').filter(project__uuid=uuid)
    ds_objs = Dataset.objects.filter(uuid__in=ds_list).order_by('name')
    infra_list = MembershipInfrastructure.objects.values_list('infrastructure__uuid').filter(project__uuid=project.uuid)
    infra_objs = Infrastructure.objects.filter(uuid__in=infra_list).order_by('name')
    project_error = None
    if request.method == "POST":
        if request.POST.get("validate"):
            project.is_valid, project_error = project_validate(ds_objs, request.user.show_uuid, project.uuid,
                                                               request.user)
        elif request.POST.get("generate_workflow"):
            generate_neo4j_user_workflow_status(project, request.user)
    if request.user.is_nsadmin or request.user.is_piadmin or request.user.is_dp or request.user.is_inp:
        wf_list = MembershipProjectWorkflow.objects.values_list('workflow__uuid').filter(
            project__uuid=project.uuid,
        )
    else:
        wf_list = MembershipProjectWorkflow.objects.values_list('workflow__uuid').filter(
            project__uuid=project.uuid,
            affiliation__uuid=request.user.ns_affiliation,
        )
    wf_objs = WorkflowNeo4j.objects.filter(uuid__in=wf_list).order_by('name')
    ig_list = MembershipComanagePersonnel.objects.values_list('person__uid', flat=True).filter(
        project__uuid=uuid,
        affiliation_ig__isnull=False
    )
    ig_objs = NotaryServiceUser.objects.filter(
        sub__in=ig_list
    ).order_by('name')
    generate_neo4j_user_workflow_status(project, request.user)
    project.save()
    return render(request, 'project_detail.html', {
        'projects_page': 'active',
        'project': project,
        'affiliations': affiliations,
        'comanage_pi_admins': comanage_pi_admins,
        'comanage_pi_members': comanage_pi_members,
        'comanage_staff': comanage_staff,
        'project_pi_admins': project_pi_admins,
        'project_pi_members': project_pi_members,
        'project_staff': project_staff,
        'datasets': ds_objs,
        'project_error': project_error,
        'workflows': wf_objs,
        'infrastructure': infra_objs,
        'institutional_governance': ig_objs,
    })


def create_new_workflow(project_obj: Project,
                        dataset_obj: Dataset,
                        template_obj: NSTemplate,
                        user_obj: NotaryServiceUser):
    workflow = WorkflowNeo4j.objects.create(
        name='neo4j_',
        description=template_obj.description,
        dataset=dataset_obj,
        template=template_obj,
        created_by=user_obj,
        created_date=timezone.now(),
        modified_by=user_obj,
        modified_date=timezone.now(),
    )
    workflow.name = 'neo4j_' + str(workflow.uuid)
    workflow.save()
    wf_created = wf_views.create_neo4j_workflow(
        graphml_file=template_obj.graphml_definition.name,
        workflow_uuid=str(workflow.uuid)
    )
    if wf_created:
        workflow.loaded_in_neo4j = True
        workflow.save()
        MembershipProjectWorkflow.objects.create(
            project=project_obj,
            dataset=dataset_obj,
            template=template_obj,
            workflow=workflow,
            is_generated=True,
        )


def project_list(request):
    try:
        person = ComanagePersonnel.objects.get(
            uid=request.user.sub,
        )
    except ComanagePersonnel.DoesNotExist:
        person = None
    if request.user.is_nsadmin:
        proj_objs = Project.objects.filter(created_date__lte=timezone.now()).order_by('name')
    elif request.user.is_ig:
        if request.method == "POST":
            if request.POST.get("ig-self-assign-project"):
                if not MembershipComanagePersonnel.objects.filter(
                        project__uuid=request.POST.get("project_uuid"),
                        person=person,
                        affiliation_ig=Affiliation.objects.get(uuid=request.user.ns_affiliation),
                ).exists():
                    MembershipComanagePersonnel.objects.create(
                        person=ComanagePersonnel.objects.get(
                            uid=request.user.sub,
                        ),
                        project=Project.objects.get(uuid=request.POST.get("project_uuid")),
                        comanage_pi_admins=None,
                        comanage_pi_members=None,
                        comanage_staff=None,
                        dataset_dso=None,
                        affiliation_ig=Affiliation.objects.get(uuid=request.user.ns_affiliation),
                        infrastructure_inp=None,
                    )
        proj_objs = Project.objects.filter(
            affiliations__idp__contains=request.user.idp,
        ).order_by('name').distinct()
    elif request.user.is_dp:
        proj_objs = Project.objects.filter(
            id__in=MembershipDatasets.objects.values('project_id').filter(
                dataset__owner=request.user.id,
            ).distinct('project_id')
        ).order_by('name')
    elif request.user.is_inp:
        proj_objs = Project.objects.filter(
            id__in=MembershipInfrastructure.objects.values('project_id').filter(
                infrastructure__owner=request.user.id,
            ).distinct('project_id')
        ).order_by('name')
    elif request.user.is_piadmin:
        proj_objs = Project.objects.filter(
            id__in=MembershipComanagePersonnel.objects.values('project_id').filter(
                person=person,
                comanage_pi_admins__isnull=False,
            ).distinct('project_id')
        ).order_by('name')
    elif request.user.is_pi:
        proj_objs = Project.objects.filter(
            id__in=MembershipComanagePersonnel.objects.values('project_id').filter(
                person=person,
                comanage_pi_members__isnull=False,
            ).distinct('project_id')
        ).order_by('name')
    elif request.user.is_staff:
        proj_objs = Project.objects.filter(
            id__in=MembershipComanagePersonnel.objects.values('project_id').filter(
                person=person,
                comanage_staff__isnull=False,
            ).distinct('project_id')
        ).order_by('name')
    else:
        proj_objs = Project.objects.filter(created_date__lte=timezone.now()).order_by('name')
    return render(request, 'projects.html', {'projects_page': 'active', 'projects': proj_objs})


def project_new(request):
    """
    Note that IG will be a self assigned attribute based on Affiliation
    :param request:
    :return:
    """
    update_comanage_group()
    update_comanage_personnel()
    if request.method == "POST":
        form = ProjectForm(request.POST, user=request.user)
        if form.is_valid():
            project = form.save(commit=False)
            project.created_by = request.user
            project.modified_by = request.user
            project.modified_date = timezone.now()
            project.save()
            # project affiliations
            for affiliiation_pk in form.data.getlist('affiliations'):
                if not MembershipAffiliations.objects.filter(
                        project=project.id,
                        affiliation=affiliiation_pk
                ).exists():
                    MembershipAffiliations.objects.create(
                        project=project,
                        affiliation=Affiliation.objects.get(id=affiliiation_pk),
                    )
            # project pi admins
            for group_pk in form.data.getlist('comanage_pi_admins'):
                if not MembershipComanagePIAdmin.objects.filter(project=project.id, comanage_group=group_pk).exists():
                    MembershipComanagePIAdmin.objects.create(
                        project=project,
                        comanage_group=ComanagePIAdmin.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanagePIAdmin.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_pi_admins=ComanagePIAdmin.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=ComanagePIAdmin.objects.get(id=group_pk),
                                comanage_pi_members=None,
                                comanage_staff=None,
                                dataset_dso=None,
                                affiliation_ig=None,
                                infrastructure_inp=None,
                            )
            # project pi members
            for group_pk in form.data.getlist('comanage_pi_members'):
                if not MembershipComanagePIMember.objects.filter(
                        project=project.id,
                        comanage_group=group_pk
                ).exists():
                    MembershipComanagePIMember.objects.create(
                        project=project,
                        comanage_group=ComanagePIMember.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanagePIMember.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_pi_members=ComanagePIMember.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=None,
                                comanage_pi_members=ComanagePIMember.objects.get(id=group_pk),
                                comanage_staff=None,
                                dataset_dso=None,
                                affiliation_ig=None,
                                infrastructure_inp=None,
                            )
            # staff / project members
            for group_pk in form.data.getlist('comanage_staff'):
                if not MembershipComanageStaff.objects.filter(project=project.id,
                                                              comanage_group=group_pk).exists():
                    MembershipComanageStaff.objects.create(
                        project=project,
                        comanage_group=ComanageStaff.objects.get(id=group_pk),
                    )
                    personnel = personnel_by_comanage_group(ComanageStaff.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=None,
                                comanage_pi_members=None,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk),
                                dataset_dso=None,
                                affiliation_ig=None,
                                infrastructure_inp=None,
                            )
            # datasets
            for ds_pk in form.data.getlist('datasets'):
                if not MembershipDatasets.objects.filter(project=project.id, dataset=ds_pk).exists():
                    # add dataset membership
                    MembershipDatasets.objects.create(
                        project=project,
                        dataset=Dataset.objects.get(id=ds_pk),
                    )
                    # add dataset provider relationship
                    dso = ComanagePersonnel.objects.get(
                        uid=NotaryServiceUser.objects.get(
                            id=Dataset.objects.get(id=ds_pk).owner_id
                        ).sub
                    )
                    MembershipComanagePersonnel.objects.create(
                        person=dso,
                        project=project,
                        comanage_pi_admins=None,
                        comanage_pi_members=None,
                        comanage_staff=None,
                        dataset_dso=MembershipDatasets.objects.get(project=project.id, dataset=ds_pk),
                        affiliation_ig=None,
                        infrastructure_inp=None,
                    )

            # infrastructure
            for inf_pk in form.data.getlist('infrastructure'):
                if not MembershipInfrastructure.objects.filter(project=project.id, infrastructure=inf_pk).exists():
                    MembershipInfrastructure.objects.create(
                        project=project,
                        infrastructure=Infrastructure.objects.get(id=inf_pk),
                    )
                    # add dataset provider relationship
                    inp = ComanagePersonnel.objects.get(
                        uid=NotaryServiceUser.objects.get(
                            id=Infrastructure.objects.get(id=inf_pk).owner_id
                        ).sub
                    )
                    MembershipComanagePersonnel.objects.create(
                        person=inp,
                        project=project,
                        comanage_pi_admins=None,
                        comanage_pi_members=None,
                        comanage_staff=None,
                        dataset_dso=None,
                        affiliation_ig=None,
                        infrastructure_inp=MembershipInfrastructure.objects.get(
                            project=project.id,
                            infrastructure=inf_pk
                        ),
                    )
            return redirect('project_detail', uuid=project.uuid)
    else:
        form = ProjectForm(user=request.user)
    return render(request, 'project_new.html', {'projects_page': 'active', 'form': form})


def project_edit(request, uuid):
    project = get_object_or_404(Project, uuid=uuid)
    update_comanage_group()
    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project, user=request.user)
        if form.is_valid():
            project = form.save(commit=False)
            project.modified_by = request.user
            project.modified_date = timezone.now()
            project.save()
            # project affiliations
            current_affiliations = MembershipAffiliations.objects.filter(project=project.id)
            for affiliation in current_affiliations:
                if str(affiliation.affiliation.id) not in form.data.getlist('affiliations'):
                    MembershipAffiliations.objects.filter(
                        project=project.id,
                        affiliation=affiliation.affiliation.id,
                    ).delete()
            for affiliiation_pk in form.data.getlist('affiliations'):
                if not MembershipAffiliations.objects.filter(
                        project=project.id,
                        affiliation=affiliiation_pk
                ).exists():
                    MembershipAffiliations.objects.create(
                        project=project,
                        affiliation=Affiliation.objects.get(id=affiliiation_pk),
                    )
            # project pi admins
            current_groups = MembershipComanagePIAdmin.objects.filter(project=project.id)
            for group in current_groups:
                if str(group.comanage_group.id) not in form.data.getlist('comanage_pi_admins'):
                    MembershipComanagePersonnel.objects.filter(
                        project=project.id,
                        comanage_pi_admins=group.comanage_group.id).delete()
                    group.delete()
            for group_pk in form.data.getlist('comanage_pi_admins'):
                if not MembershipComanagePIAdmin.objects.filter(project=project.id, comanage_group=group_pk).exists():
                    MembershipComanagePIAdmin.objects.create(
                        project=project,
                        comanage_group=ComanagePIAdmin.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanagePIAdmin.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_pi_admins=ComanagePIAdmin.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=ComanagePIAdmin.objects.get(id=group_pk),
                                comanage_pi_members=None,
                                comanage_staff=None,
                                dataset_dso=None,
                                affiliation_ig=None,
                            )
            # project pi members
            current_groups = MembershipComanagePIMember.objects.filter(project=project.id)
            for group in current_groups:
                if str(group.comanage_group.id) not in form.data.getlist('comanage_pi_admins'):
                    MembershipComanagePersonnel.objects.filter(project=project.id,
                                                               comanage_pi_members=group.comanage_group.id).delete()
                    group.delete()
            for group_pk in form.data.getlist('comanage_pi_members'):
                if not MembershipComanagePIMember.objects.filter(project=project.id, comanage_group=group_pk).exists():
                    MembershipComanagePIMember.objects.create(
                        project=project,
                        comanage_group=ComanagePIMember.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanagePIMember.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_pi_members=ComanagePIMember.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=None,
                                comanage_pi_members=ComanagePIMember.objects.get(id=group_pk),
                                comanage_staff=None,
                                dataset_dso=None,
                                affiliation_ig=None,
                            )
            # project members/staff
            current_groups = MembershipComanageStaff.objects.filter(project=project.id)
            for group in current_groups:
                if str(group.comanage_group.id) not in form.data.getlist('comanage_staff'):
                    MembershipComanagePersonnel.objects.filter(
                        project=project.id,
                        comanage_staff=group.comanage_group.id
                    ).delete()
                    group.delete()
            for group_pk in form.data.getlist('comanage_staff'):
                if not MembershipComanageStaff.objects.filter(project=project.id,
                                                              comanage_group=group_pk).exists():
                    MembershipComanageStaff.objects.create(
                        project=project,
                        comanage_group=ComanageStaff.objects.get(id=group_pk)
                    )
                    personnel = personnel_by_comanage_group(ComanageStaff.objects.get(id=group_pk).cn)
                    for person in personnel:
                        if not MembershipComanagePersonnel.objects.filter(
                                person=person,
                                project=project,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk)):
                            MembershipComanagePersonnel.objects.create(
                                person=person,
                                project=project,
                                comanage_pi_admins=None,
                                comanage_pi_members=None,
                                comanage_staff=ComanageStaff.objects.get(id=group_pk),
                                dataset_dso=None,
                                affiliation_ig=None,
                            )
            # datasets
            current_datasets = MembershipDatasets.objects.filter(project=project.id)
            for ds in current_datasets:
                if str(ds.dataset.id) not in form.data.getlist('datasets'):
                    MembershipDatasets.objects.filter(
                        project=project.id,
                        dataset=ds.dataset.id,
                    ).delete()
            for ds_pk in form.data.getlist('datasets'):
                if not MembershipDatasets.objects.filter(project=project.id, dataset=ds_pk).exists():
                    MembershipDatasets.objects.create(
                        project=project,
                        dataset=Dataset.objects.get(id=ds_pk),
                    )
            # infrastructure
            current_infra = MembershipInfrastructure.objects.filter(project=project.id)
            for infra in current_infra:
                if str(infra.infrastructure.id) not in form.data.getlist('infrastructure'):
                    MembershipInfrastructure.objects.filter(
                        project=project.id,
                        infrastructure=infra.infrastructure.id,
                    ).delete()
            for inf_pk in form.data.getlist('infrastructure'):
                if not MembershipInfrastructure.objects.filter(project=project.id,
                                                               infrastructure=inf_pk).exists():
                    MembershipInfrastructure.objects.create(
                        project=project,
                        infrastructure=Infrastructure.objects.get(id=inf_pk),
                    )
            project.is_valid = False
            project.save()
            return redirect('project_detail', uuid=project.uuid)
    else:
        form = ProjectForm(instance=project, user=request.user)
    return render(request, 'project_edit.html', {'projects_page': 'active', 'form': form, 'project_uuid': uuid})


def project_delete(request, uuid):
    project = get_object_or_404(Project, uuid=uuid)
    comanage_pi_admins = ComanagePIAdmin.objects.filter(cn__contains='-PI:admins', project=project).order_by('cn')
    comanage_pi_members = ComanagePIMember.objects.filter(cn__contains='-PI:members:active', project=project).order_by(
        'cn')
    comanage_staff = ComanageStaff.objects.filter(cn__contains='-STAFF:members:active', project=project).order_by('cn')
    ds_list = MembershipDatasets.objects.values_list('dataset__uuid').filter(project__uuid=uuid)
    ds_objs = Dataset.objects.filter(uuid__in=ds_list).order_by('name')
    wf_list = MembershipProjectWorkflow.objects.values_list('workflow__uuid').filter(project__uuid=project.uuid)
    wf_objs = WorkflowNeo4j.objects.filter(uuid__in=wf_list).order_by('name')
    infra_list = MembershipInfrastructure.objects.values_list('infrastructure__uuid').filter(project__uuid=project.uuid)
    infra_objs = Infrastructure.objects.filter(uuid__in=infra_list).order_by('name')
    affiliations = MembershipAffiliations.objects.values_list('affiliation__uuid', flat=True).filter(
        project__uuid=project.uuid,
    )
    if request.method == "POST":
        pr_wf_list = MembershipProjectWorkflow.objects.values_list('workflow__uuid').filter(
            project=project)
        pr_wf_objs = WorkflowNeo4j.objects.filter(uuid__in=pr_wf_list)
        for wf in pr_wf_objs:
            delete_workflow_by_uuid(workflow_uuid=str(wf.uuid))
            wf.delete()
        MembershipComanagePIAdmin.objects.filter(project=project.id).delete()
        MembershipComanagePIMember.objects.filter(project=project.id).delete()
        MembershipComanageStaff.objects.filter(project=project.id).delete()
        project.delete()
        return project_list(request)
    return render(request, 'project_delete.html', {
        'projects_page': 'active',
        'project': project,
        'affiliations': affiliations,
        'comanage_pi_admins': comanage_pi_admins,
        'comanage_pi_members': comanage_pi_members,
        'comanage_staff': comanage_staff,
        'datasets': ds_objs,
        'workflows': wf_objs,
        'infrastructure': infra_objs,
    })
