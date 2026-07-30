from collections import Counter

from django.core.management.base import BaseCommand

from platform_api.models import ApiInterface


class Command(BaseCommand):
    help = '按现有业务模块重新整理接口列表的模块归属'

    def handle(self, *args, **options):
        updated = 0
        for interface in ApiInterface.objects.all():
            module_name = classify_interface(interface.path, interface.name)
            if interface.module_name == module_name:
                continue
            interface.module_name = module_name
            interface.save(update_fields=['module_name', 'updated_at'])
            updated += 1

        module_counts = Counter(ApiInterface.objects.values_list('module_name', flat=True))
        self.stdout.write(self.style.SUCCESS(f'接口业务模块整理完成：更新 {updated} 条'))
        for module_name in ['首页', '个人中心', '游戏', '赛事', '活动', '后台']:
            self.stdout.write(f'{module_name}: {module_counts.get(module_name, 0)}')


def classify_interface(path, name=''):
    text = f'{path} {name}'.lower()
    if any(token in text for token in ['member', 'user', 'wallet', 'account', 'login', 'auth', 'vip', 'message']):
        return '个人中心'
    if any(token in text for token in ['promo', 'promotion', 'activity', 'bonus', 'coupon', 'reward', 'offer', 'depositquest']):
        return '活动'
    if any(token in text for token in ['casino', 'biggestwinner', 'game']):
        return '游戏'
    if any(token in text for token in ['sport', 'match', 'league', 'event', '/bet/']):
        return '赛事'
    if any(token in text for token in ['home', 'common', 'localization', 'ipinfo', 'banner', 'broadcast', 'widget']):
        return '首页'
    return '首页'
