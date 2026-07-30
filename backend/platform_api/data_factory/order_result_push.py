import base64
import binascii
from time import time
from threading import Lock
from xml.sax.saxutils import quoteattr

from ..executor import api_request_executor
from .account_balance import DataFactoryError


ORDER_RESULT_PUSH_URL = 'http://54.69.237.139:8080/api/clusters/local/topics/msg_bet_settlement/messages'

SALT = '6rx7aXuTnVtM1ZMXOgJNHX9cmibQs3vAOApvT9KPQev+v2Sa5G9QnH+E483CwmTi+gBCHZWTYLN8EMCjX94B3RPMh44WQUCS/24o75Tr97sLzz5z5ZLtFbQQDtvLgj2n'
WELLKNOWN_ABBREVIATIONS = {
    'sr:match:': '{1}', 'sr:competitor:': '(2)', 'sr:tournament:': '{3}', 'sr:simple_tournament:': '{4}',
    'sr:stage:': '{5}', 'sr:season:': '{6}', 'sr:category:': '{7}', 'sr:player:': '{8}', 'sr:venue:': '{9}',
    'sr:sport_event:': '{10}', 'sr:race_event:': '{11}', 'sr:race_tournament:': '{12}', 'sr:h2h_tournament:': '{13}',
    'sr:outright:': '{14}', 'sr:sport:': '{15}', 'sr:team:': '{16}', 'sr:simpleteam:': '{17}', 'sr:simple_team:': '{18}',
    'sr:referee:': '{19}', 'sr:market:': '{20}', 'sr:lottery:': '{21}', 'sr:draw:': '{22}', 'sr:competition_group:': '{23}',
    'codds:competition_group:': '{24}', 'mkt:': '{81}', 'variant=': '{82}', 'pre:markettext:': '{83}',
    'sr:winning_margin_no_draw:': '{84}', 'sr:exact_goals:': '{85}', 'sr:decided_by_extra_points:bestof:': '{86}',
    'sr:point_range:': '{87}', 'sr:winning_margin:': '{88}', 'sr:correct_score:bestof:': '{89}',
    'sr:correct_score:below:': '{90}', 'sr:goalscorer:fieldplayers_nogoal_owngoal_other|': '{91}',
    'sr:winner_and_rounds:': '{92}', 'sr:winning_method:': '{93}', 'ts:match:': '[1]', 'ts:competitor:': '[2]',
    'ts:tournament:': '[3]', 'ts:utour:': '[4]', 'ts:season:': '[5]', 'ts:player:': '[6]', 'ao:match:': '<1>',
    'ao:competitor:': '<2>', 'ao:tournament:': '<3>', 'ao:utour:': '<4>', 'ao:season:': '<5>', 'ao:player:': '<6>',
}
_TO_ABBR_ITEMS = None
_FROM_ABBR_ITEMS = None
_REPLACER_LOCK = Lock()


def encode(raw):
    if raw == '':
        return ''
    _validate(raw)
    return base64.b32encode(_mangle(_to_abbr(raw).encode('utf-8'))).decode('ascii').rstrip('=').lower()


def decode(encoded):
    if encoded == '':
        return ''
    return _from_abbr(_mangle(_decode_base32(encoded)).decode('utf-8'))


def decode_unsafe(encoded):
    if encoded == '':
        return ''
    try:
        decoded = _decode_base32(encoded)
        value = _from_abbr(_mangle(decoded).decode('utf-8')) if decoded else ''
        return value if _is_valid_raw(value) else ''
    except (UnicodeDecodeError, ValueError):
        return ''


def _validate(raw):
    if ':' in raw or '-' in raw:
        return
    try:
        int(raw)
    except ValueError as exc:
        raise ValueError(f'invalid raw id: {raw}') from exc


def _is_valid_raw(raw):
    return all(('0' <= char <= '9') or ('a' <= char <= 'z') or char in '-_:=@.|' for char in raw)


def _mangle(data):
    if not data:
        return b''
    last_byte = data[-1]
    salt_bytes = SALT.encode('utf-8')
    return bytes(byte ^ last_byte ^ salt_bytes[index] if index < len(data) - 1 else byte for index, byte in enumerate(data))


def _to_abbr(raw):
    return _replace(raw, False)


def _from_abbr(raw):
    return _replace(raw, True)


def _replace(raw, reverse):
    global _TO_ABBR_ITEMS, _FROM_ABBR_ITEMS
    if _TO_ABBR_ITEMS is None or _FROM_ABBR_ITEMS is None:
        with _REPLACER_LOCK:
            if _TO_ABBR_ITEMS is None or _FROM_ABBR_ITEMS is None:
                _TO_ABBR_ITEMS = list(WELLKNOWN_ABBREVIATIONS.items())
                _FROM_ABBR_ITEMS = [(value, key) for key, value in _TO_ABBR_ITEMS]
    result = raw
    for source, target in _FROM_ABBR_ITEMS if reverse else _TO_ABBR_ITEMS:
        result = result.replace(source, target)
    return result


def _decode_base32(encoded):
    padding = '=' * ((8 - len(encoded) % 8) % 8)
    try:
        return base64.b32decode((encoded + padding).upper(), casefold=True)
    except binascii.Error as exc:
        raise ValueError(str(exc)) from exc


def _xml_attribute(value):
    return quoteattr(str(value))


def build_settlement_content(*, certainty, product, event_id, market_id, specifiers, outcome_id, result, void_factor, timestamp):
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\r\n'
        f'<bet_settlement certainty={_xml_attribute(certainty)} product={_xml_attribute(product)} event_id={_xml_attribute(event_id)} timestamp={_xml_attribute(timestamp)}>'
        f'<outcomes><market id={_xml_attribute(market_id)} specifiers={_xml_attribute(specifiers)}>'
        f'<outcome id={_xml_attribute(outcome_id)} result={_xml_attribute(result)} void_factor={_xml_attribute(void_factor)} />'
        '</market></outcomes></bet_settlement>'
    )


def push_order_result(**params):
    timestamp = params.get('timestamp') or int(time() * 1000)
    submitted_event_id = str(params['event_id']).strip()
    submitted_outcome_id = str(params['outcome_id']).strip()
    event_id = decode_unsafe(submitted_event_id) or submitted_event_id
    try:
        encode(event_id)
    except ValueError as exc:
        raise DataFactoryError(f'event_id 格式无效：{exc}') from exc
    key = event_id
    try:
        outcome_id = submitted_outcome_id if submitted_outcome_id.isdecimal() else decode(submitted_outcome_id)
    except ValueError as exc:
        raise DataFactoryError(f'outcome id 格式无效：{exc}') from exc
    if not outcome_id:
        raise DataFactoryError('outcome id 解码结果为空')
    content = build_settlement_content(
        certainty=params['certainty'], product=params['product'], event_id=event_id,
        market_id=params['market_id'], specifiers=params.get('specifiers', ''),
        outcome_id=outcome_id, result=params['result'],
        void_factor=params['void_factor'], timestamp=timestamp,
    )
    payload = {'partition': 0, 'key': key, 'value': content, 'keySerde': 'String', 'valueSerde': 'String'}
    outcome = api_request_executor.execute(
        url=ORDER_RESULT_PUSH_URL, method='POST', headers={'Content-Type': 'application/json'},
        request_params=payload, assertions={'status_code': 200, 'timeout_seconds': 15},
    )
    response = outcome.response_log
    if outcome.status != 'passed':
        raise DataFactoryError(outcome.message)
    return {'key': key, 'event_id': event_id, 'outcome_id': outcome_id, 'timestamp': timestamp, 'status_code': 200, 'message': outcome.message, 'response': response, 'payload': payload}
