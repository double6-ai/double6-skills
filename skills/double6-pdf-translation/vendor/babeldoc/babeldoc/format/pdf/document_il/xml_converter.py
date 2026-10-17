# Double6 Skills 维护版本（2026-10-17）：与上游v0.5.24的修改及继承维护见 Skill 根目录 MODIFICATIONS.md；保留原作者版权与许可。
import copy
import dataclasses
from pathlib import Path

import orjson
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig

from babeldoc.format.pdf.document_il import il_version_1


class XMLConverter:
    def __init__(self):
        self.parser = XmlParser()
        config = SerializerConfig(indent="  ")
        context = XmlContext()
        self.serializer = XmlSerializer(context=context, config=config)

    def write_xml(self, document: il_version_1.Document, path: str):
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(self.to_xml(document))

    def read_xml(self, path: str) -> il_version_1.Document:
        with Path(path).open(encoding="utf-8") as f:
            return self.from_xml(f.read())

    def to_xml(self, document: il_version_1.Document) -> str:
        return self.serializer.render(document)

    def from_xml(self, xml: str) -> il_version_1.Document:
        return self.parser.from_string(
            xml,
            il_version_1.Document,
        )

    def deepcopy(self, document: il_version_1.Document) -> il_version_1.Document:
        return copy.deepcopy(document)
        # return self.from_xml(self.to_xml(document))

    def to_json(self, document: il_version_1.Document) -> str:
        def source_fields(value):
            if not dataclasses.is_dataclass(value):raise TypeError(type(value).__name__)
            return {f.name:getattr(value,f.name) for f in dataclasses.fields(value)
                    if not (f.name in {"source_text_matrix","source_local_bbox"} and getattr(value,f.name) is None)}
        return orjson.dumps(
            document,
            default=source_fields,
            option=orjson.OPT_PASSTHROUGH_DATACLASS | orjson.OPT_APPEND_NEWLINE
            | orjson.OPT_INDENT_2
            | orjson.OPT_SORT_KEYS,
        ).decode()

    def write_json(self, document: il_version_1.Document, path: str):
        with Path(path).open("w", encoding="utf-8") as f:
            f.write(self.to_json(document))
