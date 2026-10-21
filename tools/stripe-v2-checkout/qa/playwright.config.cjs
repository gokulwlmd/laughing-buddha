const {defineConfig}=require('playwright/test');
const fs=require('node:fs');
module.exports=defineConfig({testDir:'.',testMatch:'*.spec.cjs',timeout:45000,expect:{timeout:10000},workers:1,fullyParallel:false,
  reporter:[['list'],['json',{outputFile:'results/results.json'}]],outputDir:'results/artifacts',
  use:{browserName:'chromium',headless:true,viewport:{width:1440,height:1000},launchOptions:{executablePath:process.env.QA_CHROMIUM_EXECUTABLE||(fs.existsSync('/usr/bin/chromium')?'/usr/bin/chromium':undefined),args:['--no-sandbox']},screenshot:'only-on-failure'}});
