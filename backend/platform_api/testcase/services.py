import json
import zipfile
from xml.etree import ElementTree

from rest_framework.exceptions import ValidationError


XMind_MARKER_TAGS = {
    'priority-1': '待定',
    'priority-2': '冒烟',
    'priority-3': '废除',
    '1': '待定',
    '2': '冒烟',
    '3': '废除',
}


def _xmind_topic_to_node(topic):
    title = str(topic.get('title') or '').strip()
    children = topic.get('children') or {}
    attached = (children.get('attached') or []) if isinstance(children, dict) else []
    markers = topic.get('markers') or topic.get('marker-refs') or []
    marker_ids = []
    for marker in markers if isinstance(markers, list) else []:
        marker_id = marker.get('markerId') or marker.get('marker-id') if isinstance(marker, dict) else marker
        if marker_id:
            marker_ids.append(str(marker_id).lower().split('/')[-1])
    tag = next((XMind_MARKER_TAGS[item] for item in marker_ids if item in XMind_MARKER_TAGS), None)
    return {'title': title or '未命名用例', 'children': [_xmind_topic_to_node(item) for item in attached if isinstance(item, dict)], **({'tag': [tag]} if tag else {})}


def parse_xmind_package(uploaded_file):
    if not uploaded_file.name.lower().endswith('.xmind'):
        raise ValidationError('仅支持导入 .xmind 文件')
    try:
        with zipfile.ZipFile(uploaded_file) as archive:
            if 'content.json' in archive.namelist():
                sheets = json.loads(archive.read('content.json').decode('utf-8'))
                sheet = sheets[0] if isinstance(sheets, list) and sheets else {}
                topic = sheet.get('rootTopic') or sheet.get('root_topic') or {}
                node = _xmind_topic_to_node(topic)
            elif 'content.xml' in archive.namelist():
                root = ElementTree.fromstring(archive.read('content.xml'))
                topic = next((item for item in root.iter() if item.tag.endswith('topic')), None)
                if topic is None:
                    raise ValueError('未找到思维导图根节点')
                def xml_node(element):
                    title = next((item.text or '' for item in element.iter() if item.tag.endswith('title')), '')
                    children = []
                    marker_ids = [str(item.attrib.get('marker-id', '')).lower().split('/')[-1] for item in element.iter() if item.tag.endswith('marker-ref') and item.attrib.get('marker-id')]
                    def collect_topics(container):
                        for child in list(container):
                            if child.tag.endswith('topic'):
                                children.append(xml_node(child))
                            else:
                                collect_topics(child)
                    for child_container in (item for item in list(element) if item.tag.endswith('children')):
                        collect_topics(child_container)
                    tag = next((XMind_MARKER_TAGS[item] for item in marker_ids if item in XMind_MARKER_TAGS), None)
                    return {'title': title.strip() or '未命名用例', 'children': children, **({'tag': [tag]} if tag else {})}
                node = xml_node(topic)
            else:
                raise ValueError('文件中未找到 content.json 或 content.xml')
    except (zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError, ElementTree.ParseError, ValueError) as exc:
        raise ValidationError(f'XMind 文件解析失败：{exc}') from exc
    return node['title'], node
