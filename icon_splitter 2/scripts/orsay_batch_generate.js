const http = require('http');
const fs = require('fs');
const path = require('path');
const WebSocket = require('ws');

const CDP_URL = 'http://127.0.0.1:18800';
const PROMPT_DIR = '/Users/chongyu/Desktop/ICON_SP/icon_splitter 2/inputs/Tokyo___东京/prompts';
const OUTPUT_DIR = '/Users/chongyu/Desktop/ICON_SP/icon_splitter 2/inputs/Tokyo___东京/generated/底座';

const PAGES = [3, 4, 5, 6];

function cdpEval(wsUrl, expression) {
  return new Promise((resolve, reject) => {
    const ws = new WebSocket(wsUrl);
    const id = Math.floor(Math.random() * 1000000);
    ws.on('open', () => {
      ws.send(JSON.stringify({ id, method: 'Runtime.evaluate', params: { expression, returnByValue: true, awaitPromise: true } }));
    });
    ws.on('message', (data) => {
      const msg = JSON.parse(data.toString());
      if (msg.id === id) {
        ws.close();
        if (msg.error) reject(new Error(JSON.stringify(msg.error)));
        else resolve(msg.result?.result?.value);
      }
    });
    ws.on('error', reject);
    setTimeout(() => { ws.close(); reject(new Error('timeout')); }, 60000);
  });
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

async function main() {
  // 1. 获取 CDP 连接
  const targets = await new Promise((resolve, reject) => {
    http.get(`${CDP_URL}/json`, (res) => {
      let data = '';
      res.on('data', chunk => data += chunk);
      res.on('end', () => resolve(JSON.parse(data)));
    }).on('error', reject);
  });

  const page = targets.find(t => t.url && t.url.includes('orsay.alibaba-inc.com'));
  if (!page) { console.error('❌ 未找到 Orsay 页面'); process.exit(1); }
  const wsUrl = page.webSocketDebuggerUrl;
  console.log('✅ 已连接 Orsay 页面:', page.title);

  // 2. 读取 prompts
  const prompts = {};
  for (const pageNum of PAGES) {
    const file = path.join(PROMPT_DIR, `page_${String(pageNum).padStart(2, '0')}.txt`);
    prompts[pageNum] = fs.readFileSync(file, 'utf8').trim();
  }
  console.log(`✅ 已加载 ${PAGES.length} 个 prompts (Page ${PAGES.join(', ')})`);

  // 3. 创建输出目录
  fs.mkdirSync(OUTPUT_DIR, { recursive: true });

  console.log(`\n🎯 开始批量生成 ${PAGES.length} 个底座版 prompt...\n`);

  let successCount = 0;
  let failCount = 0;

  for (const pageNum of PAGES) {
    const prompt = prompts[pageNum];
    console.log(`📤 [Page ${pageNum}] 提交中... (${prompt.length} chars)`);

    try {
      // 创建 conversation
      const convResult = await cdpEval(wsUrl, `(async () => {
        const r = await fetch('/api/chat/conversation/create', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            title: 'Tokyo Page ${pageNum} 底座版',
            project_id: 73,
            user_id: '492521',
            user_name: '浪鲤',
            user_avatar: 'https://work.alibaba-inc.com/photo/492521.220x220.jpg'
          })
        });
        const data = await r.json();
        return JSON.stringify(data);
      })()`);

      const convData = JSON.parse(convResult);
      if (!convData.success) {
        console.log(`   ❌ 创建会话失败:`, convData);
        failCount++;
        continue;
      }
      const conversationId = convData.data.conversation_id;

      // 扣费
      await cdpEval(wsUrl, `(async () => {
        await fetch('/api/user/deduct_credits', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({cost: 10})
        });
      })()`);

      // 提交生成任务
      const inputContent = JSON.stringify({
        text: prompt,
        images: [],
        videos: [],
        settings: {
          resolution: '2K',
          aspect_ratio: '1:1',
          image_size: '1024x1024',
          quality: 'low'
        }
      });

      const msgResult = await cdpEval(wsUrl, `(async () => {
        const r = await fetch('/api/chat/message/create', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({
            conversation_id: '${conversationId}',
            role: 'assistant',
            message_type: 'text_to_image',
            input_content: ${JSON.stringify(inputContent)},
            original_prompt: ${JSON.stringify(prompt)},
            prompt: ${JSON.stringify(prompt)},
            model_name: 'gpt-image-2',
            generation_count: 1,
            project_id: 73,
            user_id: '492521',
            resolution: '2K'
          })
        });
        const data = await r.json();
        return JSON.stringify(data);
      })()`);

      const msgData = JSON.parse(msgResult);
      if (!msgData.success) {
        console.log(`   ❌ 提交任务失败:`, msgData);
        failCount++;
        continue;
      }

      const messageId = msgData.data.message_id;
      console.log(`   ✅ 已提交 (message_id: ${messageId})，等待生成...`);

      // 轮询等待结果
      let imageUrl = null;
      for (let attempt = 0; attempt < 30; attempt++) {
        await sleep(2000);
        
        const listResult = await cdpEval(wsUrl, `(async () => {
          const r = await fetch('/api/chat/message/list?conversation_id=${conversationId}&include_atom_tasks=true&page=1&pageSize=10&sort_order=DESC');
          const data = await r.json();
          return JSON.stringify(data);
        })()`);

        const listData = JSON.parse(listResult);
        const message = listData.data.list.find(m => m.message_id === messageId);
        
        if (!message) {
          console.log(`   ⏳ 等待中... (attempt ${attempt + 1}/30)`);
          continue;
        }

        if (message.status === 'succeeded' && message.atom_tasks && message.atom_tasks.length > 0) {
          const task = message.atom_tasks[0];
          if (task.task_output) {
            const output = JSON.parse(task.task_output);
            if (output.images && output.images.length > 0) {
              imageUrl = output.images[0].image_url || output.images[0].cdn_url;
              break;
            }
          }
        }

        if (message.status === 'failed') {
          console.log(`   ❌ 生成失败:`, message.error_message);
          break;
        }

        console.log(`   ⏳ 生成中... (${message.status}, attempt ${attempt + 1}/30)`);
      }

      if (imageUrl) {
        // 下载图片
        const outputPath = path.join(OUTPUT_DIR, `Page${String(pageNum).padStart(2, '0')}_底座_1.png`);
        console.log(`   💾 下载图片到:`, outputPath);
        
        const downloadResult = await cdpEval(wsUrl, `(async () => {
          const r = await fetch('${imageUrl}');
          const blob = await r.blob();
          const reader = new FileReader();
          return new Promise((resolve) => {
            reader.onloadend = () => resolve(reader.result);
            reader.readAsDataURL(blob);
          });
        })()`);

        const base64Data = downloadResult.split(',')[1];
        fs.writeFileSync(outputPath, Buffer.from(base64Data, 'base64'));
        console.log(`   ✅ Page ${pageNum} 完成!`);
        successCount++;
      } else {
        console.log(`   ❌ Page ${pageNum} 超时或失败`);
        failCount++;
      }

    } catch (err) {
      console.log(`   ❌ Page ${pageNum} 错误:`, err.message);
      failCount++;
    }

    await sleep(1000);
  }

  console.log(`\n🎉 完成! 成功: ${successCount}, 失败: ${failCount}`);
}

main().catch(console.error);
