"""Synthetic OOXML regression checks; these do not render Office documents."""
import argparse
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('workflow', ROOT/'scripts/ppt_workflow.py')
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)
P, A, R, PKG = workflow.NS['p'], workflow.NS['a'], workflow.NS['r'], workflow.PKG
PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aN1cAAAAASUVORK5CYII=')

def package(path, note='Spoken text', changed=False):
    relations = f'<Relationships xmlns="{PKG}"><Relationship Id="s1" Type="{R}/slide" Target="slides/slide8.xml"/><Relationship Id="s2" Type="{R}/slide" Target="slides/slide2.xml"/></Relationships>'
    deck = f'<p:presentation xmlns:p="{P}" xmlns:r="{R}"><p:sldIdLst><p:sldId id="256" r:id="s1"/><p:sldId id="257" r:id="s2"/></p:sldIdLst><p:sldSz cx="9144000" cy="5143500"/></p:presentation>'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('ppt/presentation.xml', deck)
        z.writestr('ppt/_rels/presentation.xml.rels', relations)
        z.writestr('ppt/media/pixel.png', PNG)
        for i in (8, 2):
            title = 'Changed slide' if changed and i == 8 else f'Slide {i}'
            slide = f'''<p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}"><p:cSld><p:spTree>
            <p:sp><p:nvSpPr><p:cNvPr id="2" name="title"/></p:nvSpPr><p:spPr/><p:txBody><a:p><a:r><a:t>{title}</a:t></a:r></a:p></p:txBody></p:sp>
            <p:pic><p:nvPicPr><p:cNvPr id="3" name="test image"/></p:nvPicPr><p:blipFill><a:blip r:embed="im"/><a:srcRect l="1000"/></p:blipFill><p:spPr><a:xfrm><a:off x="9200000" y="0"/><a:ext cx="914400" cy="914400"/></a:xfrm></p:spPr></p:pic>
            </p:spTree></p:cSld></p:sld>'''
            z.writestr(f'ppt/slides/slide{i}.xml', slide)
            z.writestr(f'ppt/slides/_rels/slide{i}.xml.rels', f'<Relationships xmlns="{PKG}"><Relationship Id="im" Type="{R}/image" Target="../media/pixel.png"/><Relationship Id="nt" Type="{R}/notesSlide" Target="../notesSlides/notes{i}.xml"/></Relationships>')
            z.writestr(f'ppt/notesSlides/notes{i}.xml', f'<p:notes xmlns:p="{P}" xmlns:a="{A}"><p:cSld><p:spTree><p:sp><p:nvSpPr><p:cNvPr id="2" name="notes"/><p:nvPr><p:ph type="body"/></p:nvPr></p:nvSpPr><p:txBody><a:p><a:r><a:rPr><a:solidFill><a:srgbClr val="0000FF"/></a:solidFill></a:rPr><a:t>{note}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:notes>')

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def audit(self, slides, **kwargs):
        path = self.root/'script.json'
        path.write_text(json.dumps({'slides':slides},ensure_ascii=False),encoding='utf-8')
        args = dict(source=path,expected_slides=1,min_minutes=0,cjk_rate=180,word_rate=130,require_blue=False)
        args.update(kwargs)
        return workflow.audit_script(argparse.Namespace(**args))

    def test_inventory_uses_relationship_order_and_reads_notes(self):
        path = self.root/'ordered.pptx'; package(path)
        before = path.read_bytes()
        report, code = workflow.inventory(argparse.Namespace(source=path))
        self.assertEqual(code,0)
        self.assertEqual([p['slide_part'] for p in report['pages']],['ppt/slides/slide8.xml','ppt/slides/slide2.xml'])
        self.assertEqual(report['pages'][0]['notes'],'Spoken text')
        self.assertEqual(report['pages'][0]['blue_run_count'],1)
        self.assertEqual(before,path.read_bytes())

    def test_crop_reuse_and_bounds_remain_review_candidates(self):
        path = self.root/'candidates.pptx'; package(path)
        report, code = workflow.inventory(argparse.Namespace(source=path))
        self.assertEqual(code,0)
        self.assertTrue(report['pages'][0]['pictures'][0]['has_crop'])
        self.assertEqual(len(report['repeated_media_candidates']),1)
        self.assertEqual(len(report['pages'][0]['off_slide_candidates']),1)
        self.assertIn('require visual',report['limits'])

    def test_notes_only_change_preserves_visual_parts(self):
        a,b = self.root/'a.pptx',self.root/'b.pptx'; package(a); package(b,note='Different notes')
        report,code = workflow.compare_decks(argparse.Namespace(original=a,edited=b))
        self.assertEqual(code,0)
        self.assertTrue(report['visual_parts_identical'])
        self.assertNotEqual(report['original_sha256'],report['edited_sha256'])

    def test_slide_change_is_detected(self):
        a,b = self.root/'a.pptx',self.root/'b.pptx'; package(a); package(b,changed=True)
        report,code = workflow.compare_decks(argparse.Namespace(original=a,edited=b))
        self.assertEqual(code,1)
        self.assertIn('ppt/slides/slide8.xml',report['changed_parts'])

    def test_missing_and_duplicate_pages_fail(self):
        report,code=self.audit([{'page':1,'spoken_script':'A'},{'page':1,'spoken_script':'B'}],expected_slides=2)
        self.assertEqual(code,1)
        self.assertEqual(report['missing_pages'],[2])
        self.assertEqual(report['duplicate_pages'],[1])

    def test_declared_figure_requires_an_explanation(self):
        report,code=self.audit([{'page':1,'spoken_script':'Text','figures':[{'id':'figure-a'}]}])
        self.assertEqual(code,1)
        self.assertEqual(report['pages'][0]['missing_declared_figure_explanations'],['figure-a'])

    def test_teacher_comments_are_optional_unless_requested(self):
        row={'page':1,'spoken_script':'Text'}
        self.assertEqual(self.audit([row])[1],0)
        self.assertEqual(self.audit([row],require_blue=True)[1],1)

    def test_interaction_and_teacher_cues_do_not_inflate_spoken_duration(self):
        row={'page':1,'segments':[{'spoken_text':'观察结果','teacher_cue':'提示'*500}], 'planned_interaction_seconds':600}
        report,code=self.audit([row],min_minutes=1)
        self.assertEqual(code,1)
        self.assertEqual(report['pages'][0]['cjk_characters'],4)
        self.assertLess(report['pages'][0]['estimated_spoken_minutes'],0.1)

    def test_realistic_schema_example_passes(self):
        rows=json.loads((ROOT/'examples/narration.json').read_text(encoding='utf-8'))['slides']
        self.assertEqual(self.audit(rows,require_blue=True)[1],0)

    def test_repeated_long_passages_are_reported(self):
        text='独立样本和测量单位需要核对。'*20
        report,code=self.audit([{'page':1,'spoken_script':text},{'page':2,'spoken_script':text}],expected_slides=2)
        self.assertEqual(code,0)
        self.assertTrue(report['repeated_long_fragment_candidates'])

    def test_cli_rejects_output_that_overwrites_input(self):
        path=self.root/'input.pptx'; package(path); before=path.read_bytes()
        run=subprocess.run([sys.executable,str(ROOT/'scripts/ppt_workflow.py'),'inventory',str(path),'--output',str(path)],capture_output=True,text=True)
        self.assertEqual(run.returncode,1)
        self.assertIn('must not overwrite',run.stderr)
        self.assertEqual(before,path.read_bytes())

    def test_cli_reports_invalid_zip_without_traceback(self):
        path=self.root/'bad.pptx'; path.write_bytes(b'not a zip')
        run=subprocess.run([sys.executable,str(ROOT/'scripts/ppt_workflow.py'),'inventory',str(path),'--output',str(self.root/'out.json')],capture_output=True,text=True)
        self.assertEqual(run.returncode,1)
        self.assertIn('Error:',run.stderr)
        self.assertNotIn('Traceback',run.stderr)

if __name__=='__main__':
    unittest.main()
