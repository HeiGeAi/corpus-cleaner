# Changelog

## 0.2.2

- 修复 epub 数字字符引用（&#x4E2D; 等）被抹成空格导致静默丢字，改用 html.unescape 解码。
- 修复 extract 的 getsize 竞态在异常保护外，单文件异常记 failed 不再崩整批。
- 修复 OCR 采样判定忽略 --lang 参数，与全本 OCR 口径一致。
- 修复 fix_garble 修复后 chars 字段口径与 extract 阶段不一致。
- 修复 v0.1 同名记录兼容回退可能错绑状态，绑定前校验 ext+size。
- epub 单章节解压设 50MB 上限，防 zip bomb 耗尽内存。
- README 披露 PyMuPDF AGPL-3.0 依赖许可风险。
- 依赖补上界约束并删除无引用的冗余 Pillow。
- cleanup 删除循环统一末尾落盘 + finally，消除 O(n^2) 写盘。
- 修正 notes.md 撞名算法描述（实为 sha256 后缀）；doc 转换读文件加 errors=replace；query.py 用 with 管理句柄。

## 0.2.1

- 固定清理任务的源目录与归档目录身份，拒绝预检后的根目录替换。
- 拒绝越界、symlink 与竞态路径，并为清理、转换和 OCR 增加回归测试。
