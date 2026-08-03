# AIBET Auto Vue 前端

## 启动

确保 Django 后端运行在 `http://127.0.0.1:8000`，然后：

```bash
export PATH="$HOME/.nvm/versions/node/v20.20.2/bin:$PATH"
npm install
npm run dev
```

访问 `http://127.0.0.1:4173`，使用 `admin / Aibet@123456` 登录。

Vite 开发服务器会将 `/api` 请求代理到 Django。生产构建使用 `npm run build`，构建产物输出到 `dist/`。


步骤：

1、前端部署命令

npm install
npm run build

2、创建数据库

改代码配置文件，执行建表语句


3、后端部署命令

python3 -m pip install -r requirements.txt

python3 manage.py runserver 