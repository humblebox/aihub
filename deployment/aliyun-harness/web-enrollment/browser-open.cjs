// 仅把当前网页请求触发的外部 HTTPS 打开操作返回给该请求，不维护全局待取链接。
const {AsyncLocalStorage} = require('node:async_hooks');
const {Server} = require('node:http');
const cp = require('node:child_process');
const {syncBuiltinESMExports} = require('node:module');
const scope = new AsyncLocalStorage();
const emit = Server.prototype.emit;
Server.prototype.emit = function(event, req, res, ...rest) {
  if (event === 'request' && req.method === 'POST' && req.headers['x-aihub-browser'] === '1' &&
      req.headers.origin === `https://${req.headers.host}`) {
    return scope.run(res, () => emit.call(this, event, req, res, ...rest));
  }
  return Reflect.apply(emit, this, arguments);
};
for (const method of ['execFile', 'spawn']) {
  const original = cp[method];
  cp[method] = function(file, args, ...rest) {
    const res = scope.getStore();
    if (res && !res.headersSent && !res.destroyed && ['xdg-open','/usr/bin/xdg-open'].includes(file) && Array.isArray(args) && args.length === 1) {
      let url;
      try { url = new URL(args[0]); } catch {}
      if (url?.protocol === 'https:' && !url.username && !url.password && url.href.length <= 3500) {
        res.setHeader('Cache-Control','no-store');
        res.setHeader('X-AIHub-Open',url.href);
        return original.call(this,'/usr/bin/true',[],...rest);
      }
    }
    return Reflect.apply(original,this,arguments);
  };
}
syncBuiltinESMExports();
