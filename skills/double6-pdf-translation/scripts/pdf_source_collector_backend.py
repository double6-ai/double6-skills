"""与正式backend同一入口收集源请求；在IL翻译阶段末尾强制停止，禁止typeset。"""
from pathlib import Path
import json
import os
import runpy
import sys
import pdf2zh_next_vendor as vendor
from pdf_source_cache import bound_json,file_ref,write_new


def main():
    context_ref={'path':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT'],
                 'sha256':os.environ['PAPER_TRANSLATION_SOURCE_CACHE_CONTEXT_SHA']}
    context=bound_json(context_ref)
    output=Path(context['collection_file']).parent
    original_run=runpy.run_module
    def run_with_boundary(*args,**kwargs):
        from babeldoc.format.pdf.document_il.midend.il_translator_llm_only import ILTranslatorLLMOnly
        from babeldoc.format.pdf.document_il.midend.il_translator import ILTranslator
        from babeldoc.format.pdf.document_il.midend.typesetting import Typesetting
        from babeldoc.format.pdf.document_il.xml_converter import XMLConverter
        import pdf2zh_next.high_level as high_level
        async def guarded_in_process(settings,file):
            config=high_level.create_babeldoc_config(settings,file)
            async for event in high_level.babeldoc_translate(translation_config=config):
                yield event
        # Spawn loses this collector's forced boundary; parsing settings and backend algorithm stay identical.
        high_level._translate_in_subprocess=guarded_in_process
        def forbidden_typeset(*args,**kwargs):
            write_new(output/'TYPESET_VIOLATION.json',{'violation':'source-only collection reached typesetting'})
            raise RuntimeError('source-only type-setting forbidden')
        Typesetting.typesetting_document=forbidden_typeset
        def collect(self,docs,original):
            if not self.translation_config.translator.ignore_cache:
                raise ValueError('source-only echo must bypass all backend translation cache')
            XMLConverter().write_json(docs,output/'SOURCE_IL.json')
            original(self,docs)
            write_new(output/'COLLECTION_BOUNDARY.json',{'protocol':'pdf_source_bound_cache_v1',
                'context_ref':context_ref,'source_il_ref':file_ref(output/'SOURCE_IL.json'),
                'stage':'after complete actual IL request collection; before typesetting',
                'pages':[p.page_number+1 for p in docs.page],'backend_cache_ignored':True,
                'response_origin':'source_only_nontranslation','candidate_generated':False})
            raise RuntimeError('SOURCE_ONLY_COLLECTION_COMPLETE: intentional boundary before typesetting')
        def bind(original):
            def guarded(self,docs):return collect(self,docs,original)
            return guarded
        for translator in (ILTranslatorLLMOnly,ILTranslator):
            translator.translate=bind(translator.translate)
        return original_run(*args,**kwargs)
    runpy.run_module=run_with_boundary
    return vendor.main()


if __name__=='__main__':
    raise SystemExit(main())
