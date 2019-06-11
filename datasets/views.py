import os

from django.shortcuts import render, get_object_or_404, redirect
from django.utils import timezone
from ns_workflow import Neo4jWorkflow, WorkflowError

from projects.models import Project, MembershipDatasets
from safe.dataset import mock_dataset_safe_registration
from safe.workflow import mock_workflow_safe_registration
from workflows.workflow_neo4j import create_workflow_from_template, delete_workflow_by_uuid, \
    get_neo4j_workflow_by_uuid
from .forms import TemplateForm, DatasetForm
from .jwt import encode_ns_jwt, decode_ns_jwt
from .models import NSTemplate, Dataset, MembershipNSTemplate

# string constant to display prior to registering in SAFE
SAFE_SET_FLAG = 'SET_ON_VALIDATAION'


def datasets(request):
    context = {"datasets_page": "active"}
    if request.user.is_authenticated:
        return dataset_list(request)
    else:
        return render(request, 'datasets.html', context)


def dataset_list(request):
    ds_objs = Dataset.objects.filter(created_date__lte=timezone.now()).order_by('name')
    return render(request, 'datasets.html', {'datasets_page': 'active', 'datasets': ds_objs})


def dataset_validate(tpl_objs, show_uuid):
    for template in tpl_objs:
        if not template.is_valid:
            if show_uuid:
                return False, 'Template ' + str(template.uuid) + ' is not validated'
            else:
                return False, 'Template (' + str(template.description)[:34] + '..) is not validated'
    return True, None


def dataset_detail(request, uuid):
    dataset = get_object_or_404(Dataset, uuid=uuid)
    tpl_list = MembershipNSTemplate.objects.values_list(
        'template__uuid',
    ).filter(
        dataset=dataset,
    )
    tpl_objs = NSTemplate.objects.filter(uuid__in=tpl_list).order_by('name')
    if request.method == "POST":
        dataset.is_valid, dataset_error = dataset_validate(tpl_objs, request.user.show_uuid)
        if dataset.is_valid:
            dataset.safe_identifier_as_scid = mock_dataset_safe_registration(dataset.uuid)
        dataset.save()
    else:
        dataset_error = None
    return render(request, 'dataset_detail.html', {
        'datasets_page': 'active',
        'dataset': dataset,
        'dataset_error': dataset_error,
        'templates': tpl_objs,
    })


def dataset_access(request, uuid):
    dataset = get_object_or_404(Dataset, uuid=uuid)
    dataset_error = None
    project_uuid = request.GET.get('project_uuid', '-1')
    project_name = Project.objects.get(uuid=project_uuid).name
    signed_jwt = None
    jwt_claims = None
    if request.method == "POST":
        if request.POST.get("generate-jwt"):
            signed_jwt = encode_ns_jwt(project_uuid, request.user)
            jwt_claims = decode_ns_jwt(signed_jwt)
    return render(request, 'dataset_access.html', {
        'datasets_page': 'active',
        'dataset': dataset,
        'dataset_error': dataset_error,
        'project_uuid': project_uuid,
        'project_name': project_name,
        'signed_jwt': signed_jwt,
        'jwt_claims': jwt_claims,
    })


def iframe_mock(request):
    return render(request, 'iframe_mock.html', {'home_page': 'active'})


def dataset_new(request):
    if request.method == "POST":
        form = DatasetForm(request.POST)
        if form.is_valid():
            dataset = form.save(commit=False)
            dataset.owner = request.user
            dataset.safe_identifier_as_scid = SAFE_SET_FLAG
            dataset.created_by = request.user
            dataset.modified_by = request.user
            dataset.modified_date = timezone.now()
            dataset.save()
            for template_pk in form.data.getlist('templates'):
                if not MembershipNSTemplate.objects.filter(
                        dataset=dataset.id,
                        template=template_pk
                ).exists():
                    MembershipNSTemplate.objects.create(
                        dataset=dataset,
                        template=NSTemplate.objects.get(id=template_pk)
                    )
            return redirect('dataset_detail', uuid=dataset.uuid)
    else:
        form = DatasetForm()
    return render(request, 'dataset_new.html', {'datasets_page': 'active', 'form': form})


def dataset_edit(request, uuid):
    dataset = get_object_or_404(Dataset, uuid=uuid)
    if request.method == "POST":
        form = DatasetForm(request.POST, instance=dataset)
        if form.is_valid():
            dataset = form.save(commit=False)
            dataset.modified_by = request.user
            dataset.modified_date = timezone.now()
            dataset.is_valid = False
            dataset.save()
            membership = MembershipNSTemplate.objects.filter(dataset=dataset.id)
            for member in membership:
                if str(member.template.id) not in form.data.getlist('templates'):
                    MembershipNSTemplate.objects.filter(
                        dataset=dataset.id,
                        template=member.template.id
                    ).delete()
            for template_pk in form.data.getlist('templates'):
                if not MembershipNSTemplate.objects.filter(
                        dataset=dataset.id,
                        template=template_pk
                ).exists():
                    MembershipNSTemplate.objects.create(
                        dataset=dataset,
                        template=NSTemplate.objects.get(id=template_pk)
                    )
            update_project_status_by_dataset(dataset.uuid)
            return redirect('dataset_detail', uuid=dataset.uuid)
    else:
        form = DatasetForm(instance=dataset)
    return render(request, 'dataset_edit.html', {'datasets_page': 'active', 'form': form, 'dataset_uuid': uuid})


def dataset_delete(request, uuid):
    dataset = get_object_or_404(Dataset, uuid=uuid)
    tpl_list = MembershipNSTemplate.objects.values_list(
        'template__uuid',
    ).filter(
        dataset=dataset,
    )
    tpl_objs = NSTemplate.objects.filter(uuid__in=tpl_list).order_by('name')
    used_by = dataset_in_use(uuid)
    if request.method == "POST":
        dataset.delete()
        return dataset_list(request)
    return render(request, 'dataset_delete.html', {
        'datasets_page': 'active',
        'dataset': dataset,
        'used_by': used_by,
        'templates': tpl_objs,
    })


def update_project_status_by_dataset(uuid):
    proj_list = MembershipDatasets.objects.values(
        'project__uuid'
    ).filter(dataset__uuid=uuid)
    for proj_uuid in proj_list:
        proj = Project.objects.get(uuid=proj_uuid['project__uuid'])
        proj.is_valid = False
        proj.save()


def dataset_in_use(ds_uuid):
    proj_list = MembershipDatasets.objects.values_list(
        'project__uuid',
    ).filter(
        dataset__uuid=ds_uuid,
    )
    proj_objs = Project.objects.filter(uuid__in=proj_list).order_by('name')
    return proj_objs


def template_validate(graphml_file, template_uuid):
    bolt_url = os.getenv('NEO4J_BOLT_URL')
    neo_user = os.getenv('NEO4J_USER')
    neo_pass = os.getenv('NEO4J_PASS')
    import_dir = os.getenv('NEO4J_IMPORTS_PATH_DOCKER')
    import_host_dir = os.getenv('NEO4J_IMPORTS_PATH_HOST')
    template_error = None
    is_valid = False
    try:
        delete_workflow_by_uuid(template_uuid)
    except WorkflowError as e:
        print(e)
        pass
    graphmlFile = open('./media/' + graphml_file, "r")
    graphml = graphmlFile.read()
    graphmlFile.close()
    workflow = Neo4jWorkflow(
        url=bolt_url,
        user=neo_user,
        pswd=neo_pass,
        importDir=import_dir,
        importHostDir=import_host_dir
    )
    gid = workflow.import_workflow(graphml=graphml, graphId=template_uuid)
    try:
        workflow.validate_workflow(graphId=gid)
    except WorkflowError as e:
        template_error = e
        is_valid = False
    workflow.delete_workflow(graphId=template_uuid)
    if template_error is None:
        create_workflow_from_template(graphml_file, template_uuid)
        is_valid = True
    return is_valid, template_error


def templates(request):
    context = {"templates_page": "active"}
    if request.user.is_authenticated:
        return template_list(request)
    else:
        return render(request, 'templates.html', context)


def template_list(request):
    tpl_objs = NSTemplate.objects.filter(created_date__lte=timezone.now()).order_by('name')
    return render(request, 'templates.html', {'templates_page': 'active', 'templates': tpl_objs})


def template_detail(request, uuid):
    template = get_object_or_404(NSTemplate, uuid=uuid)
    f = open(template.graphml_definition.path)
    template_file = f.read()
    f.close()
    template_error = None
    workflow_graph = get_neo4j_workflow_by_uuid(str(uuid))
    if request.method == "POST":
        if request.POST.get("validate-template"):
            template.is_valid, template_error = template_validate(template.graphml_definition.name, str(template.uuid))
            template.save()
            if template.is_valid:
                template.safe_identifier_as_scid = mock_workflow_safe_registration(template.uuid)
                template.save()
                return redirect('template_detail', uuid=template.uuid)
    return render(request, 'template_detail.html', {
        'templates_page': 'active',
        'template': template,
        'template_file': template_file,
        'template_error': template_error,
        'workflow_graph': workflow_graph,
    })


def template_new(request):
    if request.method == "POST":
        form = TemplateForm(request.POST, request.FILES)
        if form.is_valid():
            template = form.save(commit=False)
            template.owner = request.user
            template.safe_identifier_as_scid = SAFE_SET_FLAG
            template.created_by = request.user
            template.modified_by = request.user
            template.modified_date = timezone.now()
            template.save()
            return redirect('template_detail', uuid=template.uuid)
    else:
        form = TemplateForm()
    return render(request, 'template_new.html', {'templates_page': 'active', 'form': form})


def template_edit(request, uuid):
    template = get_object_or_404(NSTemplate, uuid=uuid)
    if request.method == "POST":
        form = TemplateForm(request.POST, request.FILES, instance=template)
        if form.is_valid():
            template = form.save(commit=False)
            template.modified_by = request.user
            template.modified_date = timezone.now()
            template.is_valid = False
            template.save()
            update_dataset_status_by_template(template.uuid)
            return redirect('template_detail', uuid=template.uuid)
    else:
        form = TemplateForm(instance=template)
    return render(request, 'template_edit.html', {'templates_page': 'active', 'form': form, 'template_uuid': uuid})


def template_delete(request, uuid):
    template = get_object_or_404(NSTemplate, uuid=uuid)
    used_by = template_in_use(uuid)
    if request.method == "POST":
        delete_workflow_by_uuid(str(uuid))
        template.graphml_definition.delete()
        template.delete()
        return template_list(request)
    return render(request, 'template_delete.html', {
        'templates_page': 'active',
        'template': template,
        'used_by': used_by
    })


def update_dataset_status_by_template(uuid):
    ds_list = MembershipNSTemplate.objects.values(
        'dataset__uuid'
    ).filter(template__uuid=uuid)
    for ds_uuid in ds_list:
        ds = Dataset.objects.get(uuid=ds_uuid['dataset__uuid'])
        ds.is_valid = False
        ds.save()
        update_project_status_by_dataset(ds.uuid)


def template_in_use(template_uuid):
    ds_list = MembershipNSTemplate.objects.values_list(
        'dataset__uuid',
    ).filter(
        template__uuid=template_uuid,
    )
    ds_objs = Dataset.objects.filter(uuid__in=ds_list).order_by('name')
    return ds_objs
