from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError

from ..permissions import ActionPermissionMixin
from ..responses import success
from ..models import TestCasePackage
from ..serializers import TestCasePackageSerializer
from .services import parse_xmind_package


class TestCasePackageViewSet(ActionPermissionMixin, viewsets.ModelViewSet):
    queryset = TestCasePackage.objects.select_related('created_by').all()
    serializer_class = TestCasePackageSerializer
    action_permissions = {'list': 'testcase.package.view', 'retrieve': 'testcase.package.view', 'create': 'testcase.package.create', 'update': 'testcase.package.edit', 'partial_update': 'testcase.package.edit', 'destroy': 'testcase.package.delete', 'import_xmind': 'testcase.package.create'}

    def get_queryset(self):
        queryset = super().get_queryset()
        keyword = self.request.query_params.get('keyword', '').strip()
        if keyword:
            from django.db.models import Q
            queryset = queryset.filter(Q(name__icontains=keyword) | Q(description__icontains=keyword))
        return queryset

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return success(serializer.data, '用例包创建成功', status.HTTP_201_CREATED)

    def retrieve(self, request, *args, **kwargs):
        return success(self.get_serializer(self.get_object()).data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=kwargs.pop('partial', False))
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        instance.refresh_from_db()
        return success(self.get_serializer(instance).data, '用例包更新成功')

    def destroy(self, request, *args, **kwargs):
        self.get_object().delete()
        return success(message='用例包删除成功')

    @action(detail=False, methods=['post'], url_path='import-xmind')
    def import_xmind(self, request):
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            raise ValidationError('请选择要导入的 XMind 文件')
        name, content = parse_xmind_package(uploaded_file)
        package = TestCasePackage.objects.create(name=name, content=content, created_by=request.user)
        return success(self.get_serializer(package).data, 'XMind 用例包导入成功', status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='save')
    def save_package(self, request):
        package_id = request.data.get('id')
        if package_id:
            package = self.get_queryset().filter(pk=package_id).first()
            if package is None:
                raise ValidationError('用例包不存在')
            permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
            if not (request.user.is_superuser or request.user.role.code == 'admin' or 'testcase.package.edit' in permissions):
                raise PermissionDenied('当前账号没有编辑用例包的权限')
            serializer = self.get_serializer(package, data=request.data, partial=True)
            message = '用例包更新成功'
        else:
            permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
            if not (request.user.is_superuser or request.user.role.code == 'admin' or 'testcase.package.create' in permissions):
                raise PermissionDenied('当前账号没有创建用例包的权限')
            serializer = self.get_serializer(data=request.data)
            message = '用例包创建成功'
        serializer.is_valid(raise_exception=True)
        if package_id:
            serializer.save()
            package.refresh_from_db()
        else:
            package = serializer.save(created_by=request.user)
        return success(self.get_serializer(package).data, message, status.HTTP_201_CREATED if not package_id else status.HTTP_200_OK)
