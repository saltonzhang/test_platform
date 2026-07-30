from rest_framework.exceptions import PermissionDenied


class ActionPermissionMixin:
    action_permissions = {}

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        required = self.action_permissions.get(getattr(self, 'action', ''))
        if not required or request.user.is_superuser or request.user.role.code == 'admin':
            return
        permissions = request.user.role.permissions if isinstance(request.user.role.permissions, list) else []
        if required not in permissions:
            raise PermissionDenied('当前账号没有执行此操作的权限')
