from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import ApiInterfaceViewSet, AutomationModuleViewSet, AutomationTaskResultViewSet, AutomationTaskViewSet, DashboardView, DataFactoryAccountAddView, DataFactoryAccountBalanceView, DataFactoryExecutionView, DataFactoryOrderResultPushView, EnvironmentViewSet, LoginView, MeViewSet, MonitorAlarmViewSet, MonitorApiConfigViewSet, MonitorExecutionDetailViewSet, MonitorExecutionViewSet, MonitorTaskViewSet, RoleViewSet, UserViewSet

router = DefaultRouter()
router.register('users', UserViewSet, basename='user')
router.register('roles', RoleViewSet, basename='role')
router.register('environments', EnvironmentViewSet, basename='environment')
router.register('automation/modules', AutomationModuleViewSet, basename='automation-module')
router.register('interfaces', ApiInterfaceViewSet, basename='api-interface')
router.register('automation/tasks', AutomationTaskViewSet, basename='automation-task')
router.register('automation/task-results', AutomationTaskResultViewSet, basename='automation-task-result')
router.register('monitor/interfaces', MonitorApiConfigViewSet, basename='monitor-interface')
router.register('monitor/tasks', MonitorTaskViewSet, basename='monitor-task')
router.register('monitor/executions', MonitorExecutionViewSet, basename='monitor-execution')
router.register('monitor/execution-details', MonitorExecutionDetailViewSet, basename='monitor-execution-detail')
router.register('monitor/alarms', MonitorAlarmViewSet, basename='monitor-alarm')

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='dashboard'),
    path('auth/login/', LoginView.as_view(), name='login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('auth/me/', MeViewSet.as_view({'get': 'list'}), name='me'),
    path('data-factory/account-balance/', DataFactoryAccountBalanceView.as_view(), name='data-factory-account-balance'),
    path('data-factory/account-add/', DataFactoryAccountAddView.as_view(), name='data-factory-account-add'),
    path('data-factory/order-result-push/', DataFactoryOrderResultPushView.as_view(), name='data-factory-order-result-push'),
    path('data-factory/executions/', DataFactoryExecutionView.as_view(), name='data-factory-executions'),
    path('', include(router.urls)),
]
