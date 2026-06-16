上传说明

把本目录中的文件按相对路径覆盖到你服务器上的 OIDC 项目根目录。

也就是说：

1. upload-oidc-fix/oidc/app/oidc.php
   覆盖到
   服务器 OIDC 根目录/oidc/app/oidc.php

2. upload-oidc-fix/oidc/public/index.php
   覆盖到
   服务器 OIDC 根目录/oidc/public/index.php

如果你的线上目录本身就是 oidc 项目根目录，而不是更上一层目录，
那就把 upload-oidc-fix/oidc/ 下面的内容对应覆盖进去。

本次改动不会修改数据库结构。

上传后操作：

1. 进入后台 /admin
2. 点击“公开文件补救”
   或者保存一次系统设置
3. 然后检查：
   /.well-known/openid-configuration
   /jwks.json

