"""恢复版本的行为回归：供给完整性、组合、主题、内容与安装后独立运行。"""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from double6_runtime import atomic_engine  # noqa: E402
from double6_runtime.adult_fact_projection import completion_streak, project_goal  # noqa: E402
from double6_runtime.child_playground import DEFAULT_ATOM_IDS, learning_content_selection  # noqa: E402
from double6_runtime.composition import compile_composition, composition_registry  # noqa: E402
from double6_runtime.recommendation_compiler import compile_selected_scope, validate_capability_graph  # noqa: E402
from double6_runtime.theme_system import adult_theme_registry, select_design_theme  # noqa: E402
from test_clarification_budget import ClarificationBudgetTests  # noqa: E402,F401


class RestoredRuntimeTests(unittest.TestCase):
    def test_copied_skill_builds_children_without_the_author_project(self):
        with tempfile.TemporaryDirectory() as temp:
            copied = Path(temp) / 'skill'
            copied.mkdir()
            for name in ('scripts', 'references'):
                shutil.copytree(ROOT/name, copied/name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            shutil.copy2(ROOT/'manifest.json', copied/'manifest.json')
            code = textwrap.dedent('''
                import json, sys
                from pathlib import Path
                sys.path.insert(0, str(Path(sys.argv[1])/'scripts'))
                from double6_runtime import start_run, respond, propose_from_snapshot, build
                from double6_runtime.core import read_json, ContractError
                from double6_runtime.evaluation import static_scan
                from double6_runtime.child_playground import learning_content_selection
                for stage in ('primary-transition-1-to-2','primary-transition-3-to-4'):
                    run=Path(sys.argv[2])/stage
                    current=start_run(run,'做一个儿童学习台',{'primary_domain':'education-learning','profile_id':stage,'evidence_spans':['儿童学习台']})
                    turn=1
                    while current['state']=='clarifying':
                        pending=next(row for row in read_json(run/'requirements.json')['critical_decisions'] if row['status']=='missing')
                        current=respond(run,{'event_id':f'answer-{turn}','turn_index':turn,'raw_text':'按推荐','intent':'answer','decision_id':pending['decision_id'],'normalized_value':'recommended'})
                        turn+=1
                    propose_from_snapshot(run,product_id='isolated-'+stage,title='小学学习台')
                    sha=read_json(run/'product.json')['presentation']['content_sha256']
                    respond(run,{'event_id':'product','turn_index':turn,'raw_text':'确认验证夹具','intent':'approve_product','presented_content_sha256':sha})
                    build(run)
                    result=static_scan(run)
                    assert result['status']=='pass',result['errors']
                # 原始依赖漂移必须关闭构建，不从作者项目中偷偷补齐。
                catalog=Path(sys.argv[1])/'references/child-learning-source/catalog.json'
                catalog.write_bytes(catalog.read_bytes()+b' ')
                try:
                    learning_content_selection()
                except ContractError:
                    pass
                else:
                    raise AssertionError('tampered bundled content accepted')
                print('isolated child build and integrity guard pass')
            ''')
            result = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', code, str(copied), str(Path(temp)/'runs')],
                                    capture_output=True, encoding='utf-8', cwd=temp)
            self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-2500:])

    def test_all_scenes_compile_and_keep_maturity_boundaries(self):
        result = validate_capability_graph()
        self.assertEqual(result['scene_profile_count'], 35)
        self.assertEqual(result['domain_count'], 16)
        self.assertEqual(result['scene_maturity_counts'], {'catalog_only': 10, 'contract_ready': 9, 'executable_ready': 16, 'release_ready': 0})
        scenes = json.loads((ROOT / 'references/scene-profiles.json').read_text(encoding='utf-8'))['scene_profiles']
        for scene in scenes:
            with self.subTest(scene=scene['scene_profile_id']):
                scope = compile_selected_scope(scene['scene_profile_id'])
                self.assertTrue(scope['selection_sha256'])
                composition = compile_composition(scene['scene_profile_id'], scene['recommended_module_ids'])
                self.assertEqual(composition['pack']['scene_profile_id'], scene['scene_profile_id'])

    def test_sixteen_formal_packs_keep_selected_scope_and_projection(self):
        packs = composition_registry()['packs']
        self.assertEqual(len(packs), 16)
        for pack in packs:
            with self.subTest(composition=pack['composition_id']):
                selected = set(pack['exact_module_ids'])
                compiled = compile_composition(pack['scene_profile_id'], pack['exact_module_ids'])
                self.assertEqual(set(compiled['pack']['exact_module_ids']), selected)
                for key in ('today_module_ids', 'lifecycle_module_ids', 'attention_module_ids'):
                    self.assertLessEqual(set(pack['execution_projection'][key]), selected)

    def test_all_255_child_atom_subsets_use_bundled_content(self):
        for size in range(1, len(DEFAULT_ATOM_IDS) + 1):
            for chosen in itertools.combinations(DEFAULT_ATOM_IDS, size):
                selected = learning_content_selection(list(chosen))
                self.assertEqual(selected['selected_atom_ids'], list(chosen))
                self.assertTrue(selected['eligible_item_ids'])
                self.assertEqual(len(selected['eligible_item_ids']), len(set(selected['eligible_item_ids'])))
        self.assertEqual(len(learning_content_selection()['eligible_item_ids']), 104)

    def test_six_adult_themes_validate_assets_and_lock_at_design_time(self):
        registry = adult_theme_registry()
        self.assertFalse(registry['selection_contract']['runtime_switching'])
        total = 0
        for family, value in registry['families'].items():
            scene = next(scene for scene, selected_family in registry['scene_family_map'].items() if selected_family == family)
            for theme in value['themes']:
                theme_id = theme if isinstance(theme, str) else theme['theme_id']
                self.assertEqual(select_design_theme(scene, theme_id)['theme_id'], theme_id)
                total += 1
        self.assertEqual(total, 6)

    def test_workspace_v4_import_preserves_existing_records(self):
        previous = {'schemaVersion': 4, 'contractVersion': 'double6_workspace_v1', 'productId': 'p', 'packId': 'old',
                    'modules': {'life-mood': {'records': [{'id': 'r1'}], 'starter': {}}}, 'updatedAt': '2026-08-01T00:00:00Z'}
        result = atomic_engine.migrate_workspace(previous, product_id='p', pack_id='old', storage_key='double6:p:v3')
        self.assertTrue(result['ok'])
        self.assertEqual(result['state']['modules'], previous['modules'])
        self.assertEqual(completion_streak(['2026-08-30', '2026-08-30', '2026-08-31'], as_of='2026-08-31'), 2)
        self.assertEqual(project_goal(target=21, current=7, deadline='2026-09-07', completion_dates=[], reward='', as_of='2026-08-31')['remaining'], 14)

    def test_content_and_domain_specialists(self):
        for name in ('check_personal_life', 'check_cet4_sprint', 'check_content_mines', 'check_domain_remnants',
                     'check_exam_practice', 'check_finance_tonight', 'check_fitness_tonight', 'check_teacher_class',
                     'check_household_tonight', 'check_commerce_tonight', 'check_research_tonight',
                     'check_content_tonight', 'check_sales_tonight', 'check_child_review_invariants'):
            with self.subTest(checker=name):
                # 专项脚本使用公开 CLI 输出；跨平台不依赖可执行位或 shebang。
                completed = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT/'scripts'/f'{name}.py')],
                                           capture_output=True, encoding='utf-8', cwd=ROOT)
                self.assertEqual(completed.returncode, 0, f'{name}: {(completed.stdout + completed.stderr)[-1800:]}')


if __name__ == '__main__':
    unittest.main()
