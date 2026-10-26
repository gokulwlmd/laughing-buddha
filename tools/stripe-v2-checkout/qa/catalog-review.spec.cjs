const {test,expect}=require('playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../web/master.js'),'utf8');
const component=source.slice(source.indexOf('async function renderCatalogReview(){'));
const items=JSON.parse(fs.readFileSync(path.join(__dirname,'../remaining_master_catalog.json'),'utf8')).review;

test('clarification drafts are searchable, readable and have no publish action',async({page})=>{
 await page.setContent('<main><div id="master-list"></div></main>');
 await page.evaluate(items=>{
  window.$=id=>document.getElementById(id);
  window.element=(tag,text,className)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;};
  window.card=(title,subtitle)=>{const e=element('article');e.append(element('h3',title),element('p',subtitle));return e;};
  window.api=async()=>({items});
 },items);
 await page.addScriptTag({content:component});
 await page.evaluate(()=>renderCatalogReview());
 await expect(page.locator('summary')).toHaveText('Catalog review · 243 disabled drafts needing clarification');
 await page.locator('summary').click();
 await expect(page.locator('#catalog-review-panel article')).toHaveCount(243);
 await page.getByRole('searchbox').fill('MIN-1MG-FINA-1.25MG');
 await expect(page.locator('#catalog-review-panel article')).toHaveCount(1);
 await expect(page.locator('#catalog-review-panel')).toContainText('oral capsule versus 90 mL topical liquid');
 await expect(page.locator('#catalog-review-panel button')).toHaveCount(0);
 await page.getByRole('searchbox').fill('BIW');
 await expect(page.locator('#catalog-review-panel article')).toHaveCount(16);
});
