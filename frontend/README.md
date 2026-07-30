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
