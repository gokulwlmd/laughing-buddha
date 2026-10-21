'use strict';
window.BrandDesign={
 defaults:{color:'#245844',background_color:'#f5f4ef',text_color:'#173c36',button_text_color:'#ffffff',font:'system',layout:'split'},
 fonts:{system:'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',serif:'Georgia, "Times New Roman", serif',rounded:'"Trebuchet MS", Arial, sans-serif'},
 apply(root,brand){const b={...this.defaults,...brand};for(const [field,property]of Object.entries({color:'--brand-color',background_color:'--brand-bg',text_color:'--brand-text',button_text_color:'--brand-button-text'}))if(/^#[0-9a-f]{6}$/i.test(b[field]))root.style.setProperty(property,b[field]);root.style.setProperty('--brand-font',this.fonts[b.font]||this.fonts.system);root.dataset.layout=b.layout==='stacked'?'stacked':'split';}
};
