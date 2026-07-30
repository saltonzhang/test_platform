from rest_framework.pagination import PageNumberPagination
from .responses import success


class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'pageSize'
    max_page_size = 100

    def get_paginated_response(self, data):
        return success({'list': data, 'total': self.page.paginator.count, 'page': self.page.number, 'pageSize': self.get_page_size(self.request)})
