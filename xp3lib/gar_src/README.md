# -*- coding: utf-8 -*-
"""
GARbro 加密算法原文存档(备用参考)。

来源:https://github.com/morkt/GARbro(ArcFormats 目录)
这些是 GARbro 各引擎的加密/解密原始 C# 源码,按需逐文件移植到
gar_crypt_extra.py 或对应模块。文件名带 _gar_ 前缀,勿修改。

文件列表:
- _gar_SimpleEncryption.cs      通用 ByteTransform(Xor/Not)、ByteStringEncryptedStream
- _gar_DxKey.cs                 DxLib 密钥生成(DxKey/DxKey7,已移植)
- _gar_CroixCrypt.cs            KiriKiri CroixCrypt(已移植到 gar_crypt_extra.py)
- _gar_ArcEncrypted.cs          AZSys 加密(ISAAC64,已移植)
- _gar_EncryptedGraphDat.cs     Pias 图形加密
- _gar_EncryptedStream.cs       NScripter 加密流
- _gar_Encryption.cs            Qlie 加密(V1/V2/V3)
- _gar_Primel_Encryption.cs     Primel 加密(1/2/3)
- _gar_MalieEncryption.cs       Malie 加密(Camellia 块密码)
- _gar_WarcEncryption.cs        Warc 系加密(30+ 个类:ShojoMama/YuruPlus/Testament 等)
"""
