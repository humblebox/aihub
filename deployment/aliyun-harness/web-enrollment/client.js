// AIHub 当前设备浏览器：只接收本标签页请求返回的 HTTPS 地址。
(() => {
  if (window.__aihubBrowserInstalled) return;
  window.__aihubBrowserInstalled = true;
  const fetchOriginal = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const raw = input instanceof Request ? input.url : input;
    const url = new URL(raw, location.href);
    const method = init?.method || (input instanceof Request ? input.method : 'GET');
    if (url.origin !== location.origin || method.toUpperCase() !== 'POST' || !/^\/(plugins|api)\//.test(url.pathname)) return fetchOriginal(input, init);
    const headers = new Headers(init?.headers ?? (input instanceof Request ? input.headers : undefined));
    headers.set('X-AIHub-Browser', '1');
    const response = await fetchOriginal(input, {...init, headers});
    const link = response.ok && response.headers.get('X-AIHub-Open');
    if (link) {
      const dest = new URL(link);
      if (dest.protocol === 'https:' && !dest.username && !dest.password) {
        const tab = window.open('about:blank', '_blank');
        if (tab) { tab.opener = null; tab.location.replace(dest.href); }
        else {
          const dialog = document.createElement('dialog');
          const a = document.createElement('a');
          a.href = dest.href; a.rel = 'noopener noreferrer'; a.target = '_blank';
          a.textContent = '在此设备打开 ' + dest.hostname;
          const close = document.createElement('button'); close.textContent = '关闭';
          close.onclick = () => dialog.close(); a.onclick = () => setTimeout(() => dialog.close(), 0);
          dialog.onclose = () => dialog.remove(); dialog.append(a, '　', close);
          document.body.append(dialog); dialog.showModal();
        }
      }
    }
    return response;
  };
  // 在文件链接处理器接管相对路径之前，对接入页面执行普通网页导航。
  window.addEventListener('click', event => {
    const a = event.composedPath().find(el => el instanceof HTMLAnchorElement);
    if (!a || a.origin !== location.origin || a.pathname !== '/devices' || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); event.stopImmediatePropagation(); location.assign('/devices');
  }, true);
})();
// 在设置页加入设备接入入口，手机和电脑使用同一个认证会话。
window.__ModuleLoader__.load({id:'aihub-device-enrollment',factory:(require)=>{const React=require('react');return {name:'aihub-device-enrollment',inject:['slots'],apply(ctx){const slots=ctx.get('slots');slots.inject('settings.section',()=>slots.register({name:'settings.section',id:'aihub-device-enrollment',order:39,label:()=> '添加远程设备'},()=>React.createElement('div',{style:{padding:20}},React.createElement('h2',null,'添加远程设备'),React.createElement('p',null,'直接在网页生成接入命令，在目标电脑当前项目目录粘贴即可。'),React.createElement('a',{href:'/devices',target:'_blank',rel:'noopener'},'打开设备接入页面'))))}}}});

// 代理管理沿用网页登录状态，不公开核心控制端口。
window.__ModuleLoader__.load({id:'aihub-clash-panel',factory:(require)=>{const React=require('react');return {name:'aihub-clash-panel',inject:['slots'],apply(ctx){const slots=ctx.get('slots');slots.inject('settings.section',()=>slots.register({name:'settings.section',id:'aihub-clash-panel',order:40,label:()=> 'Clash 代理'},()=>React.createElement('div',{style:{padding:20}},React.createElement('h2',null,'Clash 代理管理'),React.createElement('a',{href:'/clash',target:'_blank',rel:'noopener'},'订阅配置与服务开关' ),React.createElement('p',null,React.createElement('a',{href:'/clash/dashboard/#/setup?'+new URLSearchParams({hostname:location.hostname,port:location.port||'443',protocol:location.protocol.slice(0,-1),secondaryPath:'/clash/controller',disableUpgradeCore:'1',disableTunMode:'1'}),target:'_blank',rel:'noopener'},'进入完整代理面板')))))}}}});

// 登录密码由用户在受保护页面自行修改。
window.__ModuleLoader__.load({id:'aihub-account',factory:(require)=>{const React=require('react');return {name:'aihub-account',inject:['slots'],apply(ctx){const slots=ctx.get('slots');slots.inject('settings.section',()=>slots.register({name:'settings.section',id:'aihub-account',order:41,label:()=> '登录账号'},()=>React.createElement('div',{style:{padding:20}},React.createElement('a',{href:'/account/password',target:'_blank',rel:'noopener'},'修改登录密码'))))}}}});
