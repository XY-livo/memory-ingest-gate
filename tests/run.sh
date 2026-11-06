#!/usr/bin/env bash
# 一条命令验完：自测 + 文档里的示例流程
set -e
cd "$(dirname "$0")/.."
python3 src/gate.py selftest
python3 src/gate.py init --vault /tmp/gate-test >/dev/null
python3 src/gate.py --vault /tmp/gate-test entity add E01 "测试" >/dev/null
printf '%s' '{"layer":"L2","subject":"E01","relation":"认为","object":"测试结论","dimension":"d","valid_from":"2026-11-06","source":"t","source_ref":"inbox/t.md#L1","level":"V1","level_by":"agent","verify":"x","use_when":"y"}' > /tmp/c.json
python3 src/gate.py --vault /tmp/gate-test add --json /tmp/c.json
rm -rf /tmp/gate-test
echo "✓ tests/run.sh 通过"
