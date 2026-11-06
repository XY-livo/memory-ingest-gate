#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate.py —— 入库闸门（reference implementation, zero dependency）

一句话：**库只装"下次还用得上的判断"，不装过程。**
闸门的职责是把"看起来像结论的东西"逼到能被检验的形态，再按证据强弱分流。

用法（全部命令都接受 --vault 指定库根，默认 ./vault）：

    python3 src/gate.py init --vault vault                  # 建库骨架
    python3 src/gate.py entity add E02 "张工" --note "外部联系人"
    python3 src/gate.py similar --vault vault "同一个人两种写法"
    python3 src/gate.py add --vault vault --json claim.json  # 过闸入库
    python3 src/gate.py entity --vault vault E02             # 某实体全部记录
    python3 src/gate.py level --vault vault C-20261106-001 --to V1 --why "本机复现" --by owner
    python3 src/gate.py conflict list --vault vault
    python3 src/gate.py conflict resolve --vault vault Q-xxx --choice keep-a
    python3 src/gate.py check --vault vault                  # 全库体检
    python3 src/gate.py selftest                             # 端到端自测（不碰你的库）

设计口径（顺序本身就是逻辑）：
    ① 校验（必填 / 实体已登记 / 日期 / source_ref / level / layer / V0 定级人）
    ② 重复判（同实体+同关系+同值+区间重叠）   → 拒收，返回已有 id
    ③ 冲突判（同实体+同关系+同维度+值不同+区间重叠）→ 进 queue；V0 卷入 → needs_review
    ④ 用途闸（非"规定+V0"且无 use_when → 候选区）
    ⑤ 等级分流（V3 → 候选区 N- 前缀；V4 → refuted；其余 active）
"""
import argparse
import datetime
import json
import os
import re
import sys

LAYERS = ['L0', 'L1', 'L2', 'L3', 'L4', 'L5']
LEVELS = ['V0', 'V1', 'V2', 'V3', 'V4']
LEVEL_ORDER = {'V4': 0, 'V3': 1, 'V2': 2, 'V1': 3, 'V0': 4}   # 越大越硬
REQUIRED = ['layer', 'subject', 'relation', 'object', 'valid_from', 'source', 'level', 'level_by']


# ── 基础 ────────────────────────────────────────────────────
def now():
    return datetime.datetime.now()


def today():
    return now().strftime('%Y-%m-%d')


def ensure(vault):
    for d in ('claims', 'queue', 'inbox'):
        os.makedirs(os.path.join(vault, d), exist_ok=True)
    ent = os.path.join(vault, '_实体表.md')
    if not os.path.exists(ent):
        with open(ent, 'w', encoding='utf-8') as f:
            f.write('# 实体表\n\n| id | 名字 | 备注 |\n|---|---|---|\n')


# ── 实体 ────────────────────────────────────────────────────
def load_entities(vault):
    p = os.path.join(vault, '_实体表.md')
    out = {}
    if not os.path.exists(p):
        return out
    for line in open(p, encoding='utf-8'):
        line = line.strip()
        if not line.startswith('|'):
            continue
        cells = [c.strip() for c in line.strip('|').split('|')]
        if len(cells) < 2 or not re.match(r'^E\d+$', cells[0]):
            continue
        out[cells[0]] = {'name': cells[1], 'note': cells[2] if len(cells) > 2 else ''}
    return out


def save_entity(vault, eid, name, note=''):
    p = os.path.join(vault, '_实体表.md')
    add = '| %s | %s | %s |\n' % (eid, name, note)
    with open(p, 'a', encoding='utf-8') as f:
        f.write(add)
    return eid


def next_entity_id(vault):
    ents = load_entities(vault)
    n = 0
    for k in ents:
        n = max(n, int(k[1:]))
    return 'E%02d' % (n + 1)


# ── 条目读写（front-matter）──────────────────────────────────
FM_RE = re.compile(r'^\uFEFF?---\s*\n(.*?)\n---\s*\n', re.S)


def read_claim(path):
    txt = open(path, encoding='utf-8').read()
    m = FM_RE.match(txt)
    if not m:
        return None
    fm = {}
    for line in m.group(1).splitlines():
        mm = re.match(r'^([A-Za-z_]+):\s*(.*)$', line)
        if mm:
            fm[mm.group(1)] = mm.group(2).strip()
    fm['_path'] = path
    fm['_body'] = txt[m.end():].strip()
    fm['_history'] = re.findall(r'^-\s*(\d{4}-\d{2}-\d{2}).*$', fm['_body'], re.M)
    return fm


def write_claim(path, fm, body=''):
    keys = ['id', 'layer', 'subject', 'relation', 'object', 'condition', 'dimension',
            'valid_from', 'valid_to', 'precision', 'source', 'source_ref',
            'level', 'level_by', 'level_why', 'use_when', 'status', 'verify']
    lines = ['---']
    for k in keys:
        if k in fm and fm[k] not in ('', None):
            lines.append('%s: %s' % (k, fm[k]))
    lines.append('---')
    lines.append('')
    lines.append(body or fm.get('object', ''))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def iter_claims(vault):
    out = []
    for d in ('claims', 'queue'):
        dd = os.path.join(vault, d)
        if not os.path.isdir(dd):
            continue
        for n in sorted(os.listdir(dd)):
            if n.endswith('.md'):
                c = read_claim(os.path.join(dd, n))
                if c:
                    out.append(c)
    return out


# ── 日期 ────────────────────────────────────────────────────
def norm_date(s):
    s = (s or '').strip()
    if not s:
        return ''
    m = re.match(r'^(\d{4})(?:-(\d{1,2}))?(?:-(\d{1,2}))?$', s)
    if not m:
        raise SystemExit('日期格式不认：%s（用 2026-11-06 / 2026-11 / 2026）' % s)
    y = m.group(1)
    mo = m.group(2) or '01'
    d = m.group(3) or '01'
    return '%s-%02d-%02d' % (y, int(mo), int(d))


def expand(fm):
    prec = fm.get('precision') or '日'
    vf = norm_date(fm.get('valid_from'))
    vt = norm_date(fm.get('valid_to'))
    if prec == '年':
        vf = vf[:4] + '-01-01' if vf else ''
        vt = (vt[:4] + '-12-31') if vt else ''
    elif prec == '月':
        vf = vf[:7] + '-01' if vf else ''
        if vt:
            y, m = int(vt[:4]), int(vt[5:7])
            last = (datetime.date(y + (m // 12), (m % 12) + 1, 1) - datetime.timedelta(days=1)).day
            vt = '%s-%02d-%02d' % (y, m, last)
    fm['valid_from'] = vf
    if vt:
        fm['valid_to'] = vt
    fm['precision'] = prec
    return fm


def overlap(a1, a2, b1, b2):
    a1 = a1 or '0000-00-00'
    a2 = a2 or '9999-12-31'
    b1 = b1 or '0000-00-00'
    b2 = b2 or '9999-12-31'
    return a1 <= b2 and b1 <= a2


# ── 文本相似（给 similar 用）────────────────────────────────
CJK = re.compile(r'[\u4e00-\u9fff]+')
WRD = re.compile(r'[a-z0-9_\-]{2,}')


def toks(s):
    s = (s or '').lower()
    out = set(WRD.findall(s))
    for seg in CJK.findall(s):
        if len(seg) == 1:
            out.add(seg)
        for i in range(len(seg) - 1):
            out.add(seg[i:i + 2])
    return out


def jacc(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


# ── 闸门主体 ────────────────────────────────────────────────
def gate_add(vault, fm, dry=False):
    """返回 (ok, status, payload)。顺序：校验 → 重复 → 冲突 → 用途 → 等级。"""
    ensure(vault)
    ents = load_entities(vault)

    # ① 校验
    miss = [k for k in REQUIRED if not str(fm.get(k, '')).strip()]
    if miss:
        return False, 'reject', {'reason': '缺必填：' + ', '.join(miss)}
    if str(fm.get('layer')) not in LAYERS:
        return False, 'reject', {'reason': 'layer 只能是 ' + '/'.join(LAYERS)}
    if str(fm.get('level')) not in LEVELS:
        return False, 'reject', {'reason': 'level 只能是 ' + '/'.join(LEVELS)}
    subj = str(fm.get('subject')).strip()
    if subj not in ents:
        return False, 'reject', {'reason': '实体未登记：%s（已知：%s）' % (
            subj, '、'.join('%s=%s' % (k, v['name']) for k, v in ents.items()) or '（空）')}
    if cm := fm.get('condition'):
        pass
    # 规定类必须有 dimension
    if str(fm.get('relation')).strip() in ('规定', '规则') and not str(fm.get('dimension', '')).strip():
        return False, 'reject', {'reason': '规定类必须有 dimension（分不清是"两种说法"还是"两件事"）'}
    # V0 只能本人
    if str(fm.get('level')) == 'V0' and '本人' not in str(fm.get('level_by', '')) and 'owner' not in str(fm.get('level_by', '')).lower():
        return False, 'reject', {'reason': 'V0 是规则层，只能由本人（level_by 写 owner/本人）定'}
    # source_ref 必须能定位
    ref = str(fm.get('source_ref', '')).strip()
    if not ref:
        return False, 'reject', {'reason': 'source_ref 必须能定位（例：inbox/a.md#L12 或 event:2026-11-03 21:35）'}
    expand(fm)

    existing = iter_claims(vault)

    # ② 重复判
    for c in existing:
        if (c.get('subject') == fm['subject'] and c.get('relation') == fm['relation']
                and c.get('object') == fm['object']
                and overlap(c.get('valid_from'), c.get('valid_to'), fm['valid_from'], fm.get('valid_to'))):
            return False, 'duplicate', {'existing': c.get('id'), 'path': os.path.relpath(c['_path'], vault)}

    # ③ 冲突判
    for c in existing:
        if not (c.get('subject') == fm['subject'] and c.get('relation') == fm['relation']):
            continue
        if str(c.get('dimension', '')) != str(fm.get('dimension', '')):
            continue
        if c.get('object') == fm['object']:
            continue
        if not overlap(c.get('valid_from'), c.get('valid_to'), fm['valid_from'], fm.get('valid_to')):
            continue
        cond_diff = str(c.get('condition', '')).strip() != str(fm.get('condition', '')).strip()
        v0_involved = 'V0' in (c.get('level'), fm.get('level'))
        if cond_diff and not v0_involved:
            fm['coexist_with'] = c.get('id')
            break
        qid = 'Q-%s-%03d' % (now().strftime('%Y%m%d'), len([x for x in existing if x.get('id', '').startswith('Q-')]) + 1)
        status = 'needs_review' if v0_involved else 'pending'
        queued = dict(fm, id=qid, status=status, conflicts_with=c.get('id'),
                      question='%s 的 %s：旧「%s」vs 新「%s」——时间重叠' % (
                          ents[fm['subject']]['name'], fm['relation'], c.get('object'), fm['object']))
        if not dry:
            write_claim(os.path.join(vault, 'queue', qid + '.md'), queued)
        return True, status, {'queued': qid, 'conflicts_with': c.get('id')}

    # ④ 用途闸
    exempt = (str(fm.get('relation')).strip() in ('规定', '规则') and fm.get('level') == 'V0')
    status, why = 'active', ''
    if not exempt and not str(fm.get('use_when', '')).strip():
        status, why = 'candidate', '缺 use_when（这条将来什么时候会用到？）'
    # ⑤ 等级分流
    if fm.get('level') == 'V3':
        status, why = 'candidate', 'V3 未证实，只进候选区'
    if fm.get('level') == 'V4':
        status = 'refuted'

    cid = fm.get('id') or 'C-%s-%03d' % (now().strftime('%Y%m%d'),
                                         len([x for x in existing if str(x.get('id', '')).startswith('C-')]) + 1)
    if status == 'candidate':
        cid = cid if cid.startswith('N-') else 'N-' + cid
    fm['id'] = cid
    fm['status'] = status
    where = 'claims' if status in ('active', 'refuted') else 'queue'
    if not dry:
        write_claim(os.path.join(vault, where, cid + '.md'), fm)
    return True, status, {'id': cid, 'why': why, 'where': where}


# ── 等级升降 ────────────────────────────────────────────────
def gate_level(vault, cid, to, why, by):
    if to not in LEVELS:
        return False, 'level 只能是 ' + '/'.join(LEVELS)
    path = None
    for d in ('claims', 'queue'):
        p = os.path.join(vault, d, cid + '.md')
        if os.path.exists(p):
            path = p
            break
    if not path:
        return False, '找不到条目 ' + cid
    c = read_claim(path)
    old = c.get('level', '')
    oi, ti = LEVEL_ORDER[old], LEVEL_ORDER[to]
    up = ti > oi
    if up and ti - oi > 1:
        return False, '跳级被拒：%s → %s，本次最多到 %s' % (
            old, to, [k for k, v in LEVEL_ORDER.items() if v == oi + 1][0])
    if not up and by not in ('owner', '本人'):
        return False, '降级 agent 一律拒：只有本人（--by owner）能降'
    if to == 'V0' and by not in ('owner', '本人'):
        return False, 'V0 只能由本人定'
    hist = '\n- %s  %s→%s  by=%s  依据：%s' % (today(), old, to, by, why or '-')
    body = (c.get('_body') or '') + hist
    c['level'] = to
    c['level_by'] = by
    c['level_why'] = why
    write_claim(path, c, body)
    return True, 'ok（%s → %s）' % (old, to)


# ── 冲突裁决 ────────────────────────────────────────────────
def gate_conflict(vault, qid, choice):
    if choice not in ('keep-a', 'keep-b', 'keep-both'):
        return False, 'choice 只能是 keep-a / keep-b / keep-both'
    qp = os.path.join(vault, 'queue', qid + '.md')
    if not os.path.exists(qp):
        return False, '找不到队列条目 ' + qid
    q = read_claim(qp)
    other = q.get('conflicts_with', '')
    op = None
    for d in ('claims', 'queue'):
        p = os.path.join(vault, d, other + '.md')
        if os.path.exists(p):
            op = p
            break
    msg = []
    if choice in ('keep-a', 'keep-b'):
        drop = op if choice == 'keep-a' else qp
        keep = qp if choice == 'keep-a' else op
        if drop and os.path.exists(drop):
            c = read_claim(drop)
            c['status'] = 'superseded'
            body = (c.get('_body') or '') + '\n- %s  superseded  裁决：%s' % (today(), choice)
            write_claim(drop, c, body)
        if keep:
            c = read_claim(keep)
            c['status'] = 'active'
            write_claim(keep, c, c.get('_body'))
        msg.append('败方 → superseded')
    else:
        q['status'] = 'active'
        q.pop('question', None)
        if op:
            c = read_claim(op)
            c['coexist_with'] = q.get('id')
            write_claim(op, c, c.get('_body'))
        write_claim(qp, q, q.get('_body'))
        msg.append('两条并存（coexist_with 已记）')
    return True, '裁决完成：' + '；'.join(msg)


# ── 体检 ────────────────────────────────────────────────────
def gate_check(vault):
    probs = []
    ents = load_entities(vault)
    for c in iter_claims(vault):
        cid = c.get('id', '?')
        if c.get('subject') not in ents:
            probs.append('%s：实体 %s 未登记' % (cid, c.get('subject')))
        if not c.get('source_ref'):
            probs.append('%s：缺 source_ref' % cid)
        if c.get('level') == 'V0' and 'owner' not in str(c.get('level_by', '')).lower() and '本人' not in str(c.get('level_by', '')):
            probs.append('%s：V0 但定级人不是本人' % cid)
        if c.get('level') == 'V3' and not str(cid).startswith('N-'):
            probs.append('%s：V3 却没进候选区（应 N- 前缀）' % cid)
        if c.get('level') == 'V1' and not str(c.get('verify', '')).strip():
            probs.append('%s：V1 但没写 verify（怎么复现）' % cid)
    n_q = len([x for x in iter_claims(vault) if str(x.get('id', '')).startswith('Q-')])
    return probs, n_q


# ── 自测 ────────────────────────────────────────────────────
def selftest():
    import shutil
    import tempfile
    vault = tempfile.mkdtemp(prefix='gate-selftest-')
    fails = []

    def expect(cond, what):
        if not cond:
            fails.append(what)

    ensure(vault)
    eid = save_entity(vault, 'E01', '测试实体')
    base = dict(layer='L2', subject=eid, relation='认为', valid_from='2026-11-01',
                source='test', source_ref='inbox/t.md#L1', level='V1', level_by='agent',
                verify='跑 python -c "print(1)" 输出 1', use_when='遇到同类判断时')

    ok, st, res = gate_add(vault, dict(base, object='甲方案可行'))
    expect(ok and st == 'active', '正常入库应 active，实际 %s %s' % (st, res))

    ok, st, res = gate_add(vault, dict(base, object='甲方案可行'))
    expect(not ok and st == 'duplicate', '重复应被拒，实际 %s' % st)

    ok, st, res = gate_add(vault, dict(base, object='乙方案可行', condition='小规模'))
    expect(ok and st in ('pending', 'candidate', 'active'), '条件不同应可并存或入队，实际 %s' % st)

    ok, st, res = gate_add(vault, dict(base, object='丙', level='V0', level_by='agent'))
    expect(not ok and 'V0' in res.get('reason', ''), 'agent 写 V0 应被拒')

    # 下面几项换一个实体，避免与上面的"甲/乙"形成冲突（冲突优先于用途/等级分流）
    e2 = save_entity(vault, 'E02', '测试实体二')
    base2 = dict(base, subject=e2, relation='认为')

    ok, st, res = gate_add(vault, dict(base2, object='丁', use_when='', dimension='d1'))
    expect(ok and st == 'candidate', '缺 use_when 应进候选区，实际 %s' % st)

    ok, st, res = gate_add(vault, dict(base2, object='戊', level='V3', dimension='d2'))
    expect(ok and st == 'candidate' and res['id'].startswith('N-'), 'V3 应进候选区且 N- 前缀，实际 %s/%s' % (st, res.get('id')))

    ok, st, res = gate_add(vault, dict(base2, object='己', level='V4', dimension='d3'))
    expect(ok and st == 'refuted', 'V4 应 refuted，实际 %s' % st)

    ok, st, res = gate_add(vault, dict(base2, object='庚', relation='规定', dimension=''))
    expect(not ok and 'dimension' in res.get('reason', ''), '规定类缺 dimension 应被拒')

    first = [c for c in iter_claims(vault) if c.get('object') == '甲方案可行'][0]['id']
    ok, msg = gate_level(vault, first, 'V0', '试升', 'agent')
    expect(not ok and 'V0' in msg, 'agent 不能升 V0')
    ok, msg = gate_level(vault, first, 'V2', '降一档', 'agent')
    expect(not ok and '降级' in msg, 'agent 不能降级')
    ok, msg = gate_level(vault, first, 'V2', '降一档', 'owner')
    expect(ok, '本人可以降级')

    v3 = [c for c in iter_claims(vault) if c.get('level') == 'V3'][0]['id']
    ok, msg = gate_level(vault, v3, 'V1', '试跳级', 'owner')
    expect(not ok and '跳级' in msg, 'V3→V1 应判跳级，实际 %s' % msg)

    probs, nq = gate_check(vault)
    expect(isinstance(probs, list), '体检要返回列表')
    shutil.rmtree(vault, ignore_errors=True)

    if fails:
        print('✗ 自测失败 %d 项：' % len(fails))
        for f in fails:
            print('  - ' + f)
        return 1
    print('✓ 自测通过：入库 / 重复 / 条件并存 / V0 越权 / 缺 use_when / V3 候选 / V4 refuted / 规定类 dimension / 升降级四条规则 / 体检')
    return 0


# ── CLI ────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description='入库闸门（reference implementation）')
    ap.add_argument('--vault', default='vault', help='库根目录，默认 ./vault')
    sub = ap.add_subparsers(dest='cmd')

    sub.add_parser('init', help='建库骨架')
    p = sub.add_parser('entity', help='实体：add / 列出 / 查某实体')
    p.add_argument('args', nargs='*')
    p.add_argument('--note', default='')
    p.add_argument('--add', default='', help='"名字" 简写')

    p = sub.add_parser('add', help='过闸入库（--json 文件 或 --stdin）')
    p.add_argument('--json', default='')
    p.add_argument('--dry', action='store_true')

    p = sub.add_parser('similar', help='像不像已有条目')
    p.add_argument('text')

    p = sub.add_parser('level', help='等级升降')
    p.add_argument('id')
    p.add_argument('--to', required=True)
    p.add_argument('--why', default='')
    p.add_argument('--by', default='agent')

    p = sub.add_parser('conflict', help='冲突队列 list / resolve')
    p.add_argument('op')
    p.add_argument('qid', nargs='?')
    p.add_argument('--choice', default='')

    sub.add_parser('check', help='全库体检')
    sub.add_parser('selftest', help='端到端自测')

    # 让 --vault 能放在子命令后面（argparse 默认只认顶层位置）
    for name, sp in list(sub.choices.items()):
        sp.add_argument('--vault', default=None, help='库根目录（可放子命令后）')

    a = ap.parse_args()
    if getattr(a, 'vault', None) is None:
        a.vault = ap.get_default('vault') if hasattr(ap, 'get_default') else 'vault'
    if a.cmd == 'selftest':
        return selftest()
    if a.cmd == 'init':
        ensure(a.vault)
        print('✓ 已建库：%s（claims/ queue/ inbox/ _实体表.md）' % a.vault)
        return 0

    if a.cmd == 'entity':
        ensure(a.vault)
        ents = load_entities(a.vault)
        if not a.args and not a.add:
            for k, v in sorted(ents.items()):
                print('%s  %s  %s' % (k, v['name'], v['note']))
            return 0
        if a.add:
            eid = next_entity_id(a.vault)
            save_entity(a.vault, eid, a.add, a.note)
            print('✓ 已登记 %s = %s' % (eid, a.add))
            return 0
        if a.args and a.args[0] == 'add':
            name = a.args[2] if len(a.args) > 2 else a.args[1]
            eid = a.args[1] if len(a.args) > 2 else next_entity_id(a.vault)
            save_entity(a.vault, eid, name, a.note)
            print('✓ 已登记 %s = %s' % (eid, name))
            return 0
        sid = a.args[0]
        rows = [c for c in iter_claims(a.vault) if c.get('subject') == sid]
        if not rows:
            print('（%s 没有记录）' % sid)
            return 0
        for c in rows:
            print('%-22s %-3s %s' % (c.get('id'), c.get('level'), c.get('object')))
        return 0

    if a.cmd == 'add':
        ensure(a.vault)
        fm = json.load(open(a.json, encoding='utf-8')) if a.json else json.load(sys.stdin)
        ok, status, payload = gate_add(a.vault, fm, dry=a.dry)
        print(json.dumps({'ok': ok, 'status': status, **payload}, ensure_ascii=False))
        return 0 if ok else 1

    if a.cmd == 'similar':
        rows = []
        t = toks(a.text)
        for c in iter_claims(a.vault):
            s = jacc(t, toks(c.get('object', '') + ' ' + c.get('condition', '')))
            if s >= 0.15:
                rows.append((s, c))
        rows.sort(key=lambda x: -x[0])
        if not rows:
            print('（没找到相近条目 —— 可以新建）')
            return 0
        for s, c in rows[:5]:
            print('%.2f  %-22s %-3s %s' % (s, c.get('id'), c.get('level'), c.get('object')))
        return 0

    if a.cmd == 'level':
        ok, msg = gate_level(a.vault, a.id, a.to, a.why, a.by)
        print(('✓ ' if ok else '✗ ') + msg)
        return 0 if ok else 1

    if a.cmd == 'conflict':
        if a.op == 'list':
            qs = [c for c in iter_claims(a.vault) if str(c.get('id', '')).startswith('Q-')]
            if not qs:
                print('（队列空）')
                return 0
            for c in qs:
                print('%-24s %-12s %s' % (c.get('id'), c.get('status'), c.get('question', '')[:70]))
            return 0
        if a.op == 'resolve':
            ok, msg = gate_conflict(a.vault, a.qid, a.choice)
            print(('✓ ' if ok else '✗ ') + msg)
            return 0 if ok else 1

    if a.cmd == 'check':
        probs, nq = gate_check(a.vault)
        print('队列待裁决：%d 条' % nq)
        if not probs:
            print('✓ 全库无问题')
            return 0
        for p in probs:
            print('✗ ' + p)
        return 3

    ap.print_help()
    return 0


if __name__ == '__main__':
    sys.exit(main())
