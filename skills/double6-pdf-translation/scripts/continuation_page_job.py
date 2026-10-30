"""在有界子进程中执行一页既有 candidate，保留完整结构化结果。"""
import contextlib
import json
from pathlib import Path
import sys


def main():
    config = json.loads(Path(sys.argv[1]).read_text())
    if not config['arguments'] or config['arguments'][0] != 'candidate':
        raise ValueError('continuation worker requires candidate')
    import paper_translation_workflow
    path = Path(config['result'])
    with path.open('w') as stream, contextlib.redirect_stdout(stream):
        code = paper_translation_workflow.main(config['arguments'])
    return code


if __name__ == '__main__':
    raise SystemExit(main())
