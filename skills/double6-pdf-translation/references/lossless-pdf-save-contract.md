# PDF 无损减容

冻结输入 SHA 和统一保存参数后，`scripts/lossless_pdf_save.py` 的 `save_candidate` 生成独立候选文件。参数为 garbage=4、clean=False、deflate=True、deflate_images=True、deflate_fonts=True、no_new_id=True、use_objstms=1、preserve_metadata=True；实际 runtime 必须支持完整参数集。方法根据 [PyMuPDF Document.save 官方说明](https://pymupdf.readthedocs.io/en/latest/document.html#Document.save) 去重对象及流，并压缩原始数据。没有图像重采样、字体子集化或正文重排。

仅支持未修复、未加密、无签名/表单的 1–20 页 PDF；不覆盖输入及已有输出，不接受页码、URI、字体或坐标例外。第一方调用必须使用仓库锁定环境，在项目同锁的 2GiB/120秒 runner 下运行。保存先做小规模 smoke，核验逐页打开，单批最多5页，不能一次缓存全文图像。运行期间监控进程和系统内存。

`verify_document_metadata` 检查元数据、XMP、目录、页标签和嵌入文件。`verify_page` 检查每页几何、全部实际字符/GID/字体/样式/位置、解码内容流、真实字体数据、解码图像及mask、Form流、完整注释字段、实际链接目的地、矢量画面以及144dpi整页像素。页对象重新编号时，内部目的地按实际页身份归一化；引用循环、过深引用、超页数/字符预算或任一差异均停止。保存成功和体积变小不证明通过；所有已声明页面核验通过后，才允许作为质量不变的减容版本交付。独立整体验收、用户本人接受和 strict 晋升分别登记。

输入合同与样例：`schemas/lossless-pdf-save.schema.json`、`examples/lossless-pdf-save.example.json`；复核提示：`prompts/lossless-pdf-save-review.md`。样例仅示意字段，须替换为实际冻结身份。本方法没有被证实覆盖扫描件、复杂表单、签名文件或超过20页的输入。

2026-10-11 实际验证范围：当前主论文13页和原生2页。主论文789574576→57034218字节，原生41882757→28050828字节；全15页逐页字形/真实字体/资产/动作/画面一致，独立审校另行按最终 SHA 出具证据。证据入口：`projects/paper-translation/outputs/lossless_overall_20261011_night/README.md`。Skill 2.0.0 仍未发布。
