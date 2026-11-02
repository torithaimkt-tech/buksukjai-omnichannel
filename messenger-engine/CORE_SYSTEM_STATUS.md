# สรุปสถานะแกนกลางระบบแชทบอท (Central Omnichannel AI Chatbot Core Status)
**อัปเดตล่าสุด:** 2 พฤศจิกายน 2026 (เวลา 10:12 น.)
**โฟลเดอร์แกนกลาง:** `D:\chat bot\messenger-engine`
**เซิร์ฟเวอร์ออนไลน์ (Cloud URL):** `https://buksukjai-omnichannel.onrender.com`
**GitHub Repositories:**
- `origin`: `https://github.com/pordiporditeam-sudo/buksukjai-omnichannel.git`
- `render-origin`: `https://github.com/torithaimkt-tech/buksukjai-omnichannel.git`

---

## 1. สิ่งที่ทำเสร็จสมบูรณ์และเปิดใช้งานในแกนกลางแล้ว (Completed & Active)

### 1.1 โครงสร้างเซิร์ฟเวอร์และการรันบน Cloud (Render.com)
- **ย้ายจาก Railway / Zeabur มาใช้ Render.com สำเร็จแล้ว:**
  - Railway ปิดรับสมัครสมาชิกใหม่ชั่วคราวหลังเหตุการณ์ล่มเมื่อ 21 ต.ค. และ Zeabur ประกาศปิดตัววันที่ 31 ธ.ค. 2026 จึงใช้ **Render.com** แทนค่ะ
  - สร้างไฟล์ Blueprint อัตโนมัติ (`D:\chat bot\render.yaml`) ตั้งค่าโซน `singapore` รันเครื่องเดียวดูแลครบทุกเพจค่ะ
  - สร้างกล่องเก็บกุญแจ **Environment Group (`buksukjai-omnichannel-env`)** บน Render Dashboard (`Tori's workspace`) บันทึกตัวแปร `.env` ครบ 14 รายการเรียบร้อยแล้วค่ะ
  - ออนไลน์จริงที่ `https://buksukjai-omnichannel.onrender.com` พร้อมระบบ Auto-sync LINE Webhook อัตโนมัติเมื่อเซิร์ฟเวอร์เริ่มทำงานค่ะ

### 1.2 ช่องทางและบอทที่เชื่อมต่อสำเร็จแล้ว (Connected Channels & Bots)
1. **แบรนด์ ข้าวบุกสุขใจ (`brand_id: buksukjai` — Slot 1):**
   - **Facebook Messenger:** เชื่อมต่อเพจ `806129109240845` พร้อม `PAGE_ACCESS_TOKEN` ใช้งานจริงแล้วค่ะ
   - **LINE OA (`@602xbpha`):** เชื่อมต่อ `LINE_CHANNEL_SECRET` และ `LINE_CHANNEL_ACCESS_TOKEN` ใช้งานจริงแล้วค่ะ
   - **ไฟล์ความรู้และโปรโมชั่น:** ใช้ `messenger-engine/config.json` ครบถ้วนค่ะ
2. **บอทผู้ช่วยสรุปงานและแจ้งเตือนในกลุ่ม LINE (`brand_id: workbot` — Slot 5, `@934ndvfs` GENIUS POINT):**
   - เชื่อมต่อกับกลุ่ม LINE ทำงาน 2 กลุ่ม (`C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`)
   - ส่งรายงานยอดขายและสต็อกประจำวันเวลา 07:00 น. อัตโนมัติค่ะ
   - แจ้งเตือนเข้ากลุ่มทันทีเมื่อ AI ไม่มั่นใจคำตอบ พร้อมรองรับการ Quote-Reply หรือพิมพ์ `#Q` / `ตอบ:` จากในกลุ่มเพื่อส่งคำตอบกลับไปหาลูกค้าโดยตรงค่ะ
3. **บอทโค้ชสอนงาน AI (`brand_id: coachbot` — Slot 6, `@346zyzej` Muzart พามู):**
   - แยกบอทเฉพาะสำหรับกลุ่ม Comment (`Cf0c8835b5b0711e80f7350ffc9af66f1`) เพื่อรับคอมเมนต์และรูปแคปหน้าจอจากคุณนัด/คุณแอมมี่มาสอน AI และอัปเดตกฎเข้าแกนกลางอัตโนมัติค่ะ

### 1.3 ระบบตรวจสอบคุณภาพคำตอบและกฎเหล็กในแกนกลาง (Audit Gate & Learned Rules)
บันทึกถาวรอยู่ใน `messenger-engine/line_group_config.json`, `messenger-engine/audit_lessons_learned.json`, `app/prompt_engine.py`, และ `app/audit.py`:
- **กฎน้ำเสียงอบอุ่นเป็นธรรมชาติ:** ห้ามตัดบทถามห้วนๆ ว่า `"คุณลูกค้าสนใจรับขนาดเท่าไหร่ค่ะ"` หรือส่งตารางโปรซ้ำโดยไม่ตอบคำถามลูกค้าให้ตรงประเด็นก่อนค่ะ
- **กฎป้องกันคำขอบคุณตกหล่น (บทเรียนเคสคุณ Gus Sasi):** บังคับใช้ `"ยินดีมากๆ เลยค่ะ"` หรือ `"ด้วยความยินดีเลยค่ะ"` เสมอ มีระบบกรองคำผิด `"ดีมากๆค่ะ"` (ตกคำว่า ยิน) อัตโนมัติใน `llm.clean_chat_text()` และ `audit.py` ค่ะ
- **กฎทวนออเดอร์และปิดการขายทันที (บทเรียนเคสคุณโชกุน Jt Shogun Tj):** เมื่อลูกค้าแจ้งขนาด + ชื่อ-ที่อยู่-เบอร์โทร + เลือกเก็บเงินปลายทางครบถ้วนแล้ว ให้ทวนออเดอร์ แนบ `#BUY<ยอดเงิน>` แยกกล่องเดี่ยว และกล่าวขอบคุณแจ้งจัดส่งทันที (`state='completed'`, `image_key='none'`) **ห้ามส่งรูปโปรโมชั่นซ้ำ และห้ามบอกให้ลูกค้าพิมพ์คำว่า "ยืนยัน" ซ้ำอีกเด็ดขาดค่ะ**
- **คลังคำถามพบบ่อยที่เรียนรู้เพิ่ม (Learned FAQ):**
  - **เรทราคาส่ง (100 ถุง):** 60g ถุงละ 25.- (2,500.-) / 500g ถุงละ 165.- (16,500.-) / 1kg ถุงละ 290.- (29,000.-) ไม่รวมค่าส่งตามจริงค่ะ
  - **อายุการเก็บรักษา:** เก็บได้นาน 1 ปีในอุณหภูมิห้องปกติ ไม่จำเป็นต้องแช่ตู้เย็นค่ะ

### 1.4 ระบบเชื่อมคลังสินค้า JST ERP, ติดตามพัสดุ และรายงานยอดขาย (`app/jst_erp.py`, `app/parcel_tracker.py`, `app/daily_sheet_report.py`)
- **ระบบติดตามพัสดุ 2 ระยะ (`parcel_tracker.py`):** แจ้งเลขพัสดุ J&T Express เมื่อของออกจากคลัง (Stage 1) และแจ้งเตือนเมื่อพัสดุนำจ่ายสำเร็จ (Stage 2) พร้อมชุดข้อความสุ่มที่เป็นธรรมชาติค่ะ
- **ระบบตรวจสอบขนส่งใน JST ERP:** แก้ไขออเดอร์ที่ขาดการผูกขนส่ง (`NoExpress`) ให้ผูก J&T Express (`219956`) อัตโนมัติค่ะ
- **ระบบป้องกันออเดอร์ซ้ำใน JST ERP และรายงานประจำวัน:**
  - ปิด `AUTO_SYNC_ENABLED = False` โดยค่าเริ่มต้นเพื่อไม่ให้บอทคีย์ออเดอร์ `"FB: ..."` ซ้ำซ้อนกับที่แอดมินคีย์มือตอนกลางคืนค่ะ
  - ขยายการเช็กออเดอร์ซ้ำ (`check_duplicate_order`) เป็น 30 วัน และข้ามรายการเคลมสินค้า (`⭕เคลม⭕`) ไม่ให้นับเป็นออเดอร์ขายใหม่ค่ะ
  - กรองออเดอร์ซ้ำในรายงานประจำวัน (`daily_sheet_report.py`) โดยยึดออเดอร์จริงจาก JST ERP ที่ตัดรายการยกเลิกและรายการซ้ำออกแล้วค่ะ
- **แม่แบบ n8n Workflows (`messenger-engine/n8n_workflows/`):** สร้างไฟล์ JSON แม่แบบทั้ง 4 โฟลว์ (`1_buksukjai_sales_bot.json`, `2_buksukjai_summary_bot.json`, `3_buksukjai_ai_coach_bot.json`, `4_torimarketing_admin_bot.json`) เตรียมไว้เรียบร้อยแล้วค่ะ

### 1.5 การรวบรวมประวัติแชท Facebook Messenger ทั้ง 3 เพจ และสกัดคลังคำถามเข้าแกนกลาง (Completed)
- **รวมไฟล์ประวัติแชทชุดใหม่ (16 ก.ย. – 29 ต.ค. 2026 จำนวน `5,445` แชท / `97,251` ข้อความ) เข้ากับของเดิมและตัดซ้ำเรียบร้อยแล้ว:**
  1. **เพจ ข้าวบุก สุขใจ (`buksukjai`):** รวมสุทธิ **`8,408 แชท` (`166,489 ข้อความ`)** (27 เม.ย. – 29 ต.ค. 2026 ต่อเนื่องครบ 100%) เก็บที่ `D:\pordisuk project\commentandmessage\buksukjai`
  2. **เพจ ข้าวบุกหอมมะลิ มิสเตอร์บุก (Mister Buk เพจ 1):** รวมสุทธิ **`4,497 แชท` (`79,184 ข้อความ`)** (13 ต.ค. 2025 – 29 ต.ค. 2026 ต่อเนื่องครบ 100%) เก็บที่ `D:\pordisuk project\commentandmessage\misterbukkrice page 2` และ `C:\Users\PC\Downloads\mrbuk\messages page 1`
  3. **เพจ Mr.Buk มิสเตอร์บุก (Mister Buk เพจ 2 - เพจหลัก):** รวมสุทธิ **`10,301 แชท` (`201,070 ข้อความ`)** เก็บที่ `C:\Users\PC\Downloads\mrbuk\messages page 2` และ `D:\pordisuk project\commentandmessage\mrbukrice`
  - **รวมทั้งหมด 3 เพจ:** **`23,206 แชท` (`446,743 ข้อความ`)**
- **อัปเดตฐานข้อมูลลูกค้าและรายงานวิเคราะห์ครบทุกไฟล์แล้ว:**
  - `D:\pordisuk project\customer_database_output\customers.csv` & `meta_upload_all.csv`: ลูกค้าซื้อจริง (มีเบอร์โทร + วิธีชำระเงิน ตัดซ้ำแล้ว) เพิ่มจาก `1,824` ราย เป็น **`3,722` ราย** (โอนเงิน `1,311` ราย / COD `2,605` ราย)
  - `D:\pordisuk project\customer_database_output\collab_offers_leads.csv`: รายชื่อผู้ติดต่อขอราคาส่ง/ตัวแทนจำหน่าย (`46` ราย), อินฟลูเอนเซอร์ (`5` ราย), พาร์ทเนอร์ OEM (`3` ราย) รวม **`54` ราย**
  - `C:\Users\PC\Downloads\mrbuk\Mr_Buk_Summary.docx`: อัปเดตรายงานวิเคราะห์แชท Mister Buk ทั้ง 2 เพจ (`14,798` แชท)
  - **ซิงก์คลัง FAQ ทั้ง 20 หมวดคำถาม + เรทราคาส่ง 100 ถุง + กฎเหล็กทั้งหมด ลงในทั้ง `messenger-engine/config.json`, `messenger-engine/config_mrbuk.json`, และ `D:\chat bot\config.json` ตรงกันครบ 100% แล้วค่ะ**

### 1.6 กฎเหล็กการแยกแบรนด์/บริษัทเด็ดขาด 100% และการเตรียมชื่อ + รูปโปรไฟล์บอทส่งรีพอร์ต (`workbot` @934ndvfs)
- **🔒 กฎเหล็กห้ามปะปนกับบริษัทใหม่เด็ดขาด 100% (Strict Shareholder & Company Isolation Rule):**
  - ระบบแชทบอทนี้และกลุ่ม LINE สรุปรายงานเป็นของโปรเจกต์ **มิสเตอร์บุก (`Mr.Buk`)** และ **ข้าวบุกสุขใจ (`Buk Sukjai`)** ซึ่งคุณนัดมีหุ้นส่วนฝั่งเดิมที่ **ไม่รู้เรื่องบริษัท พอดิพอดี เฮาส์ จำกัด (`Pordipordi House`) และแบรนด์พอดีสุข (`Pordisuk`) เลยแม้แต่นิดเดียว และห้ามรู้เด็ดขาด 100%**
  - ดังนั้น **ห้ามนำชื่อ `Pordipordi` / `พอดิพอดี` / `พอดีสุข` / ชื่อมาสคอต (`ทูลี่` / `ขุนสุข`) หรือสิ่งใดที่เชื่อมโยงกับบริษัทใหม่มาใช้ตั้งชื่อบอท รูปโปรไฟล์ หรือข้อความแจ้งเตือนในระบบนี้และในกลุ่ม LINE เด็ดขาดค่ะ** ต้องแยกขาดออกจากกันอย่างสิ้นเชิง
- **รายชื่อบอทส่งรีพอร์ตที่ปลอดภัย 100% (สำหรับใช้เปลี่ยนแทนชื่อบริษัทเก่า `GENIUS POINT`):**
  - *แนวระบบรีพอร์ตกลางๆ (แนะนำ):* **`Daily Report Bot`**, `Smart Report Center`, `Sales & Chat Report`, `Auto Report Hub`, `Admin Report Bot`
  - *แนวผู้ช่วยสรุปยอด:* **`บอทสรุปรีพอร์ต (Daily Report)`**, `น้องรีพอร์ต · สรุปยอด`, `ผู้ช่วยรายงานประจำวัน`, `เลขาสรุปยอด (Report Bot)`, `Boty Report`
  - *แนวผูกกับข้าวบุก 2 แบรนด์นี้โดยตรง:* **`Buk Report Bot`**, `Mr.Buk & Sukjai Report`, `Buk Daily Report (สรุปยอดข้าวบุก)`, `Buk Team Report`
- **คำสั่งสร้างรูปโปรไฟล์ตัวการ์ตูน 1:1 (Centered Avatar Composition ไม่โดนตัดขอบวงกลม) ทั้ง 3 สไตล์:**
  1. **สไตล์ที่ 1 (น้องหุ่นยนต์ผู้ช่วยอัจฉริยะ 3D Pixar-Style):**
     `A cute 3D Pixar-style chibi robot assistant designed as a social media profile avatar, 1:1 square aspect ratio, centered head-and-shoulders composition. The friendly mini robot has a glossy white and mint-green body, wearing smart rimless glasses and a tiny neat bowtie. Its digital LED face screen shows a cheerful, confident smiling expression. It is holding a glowing futuristic tablet displaying an upward green bar chart and a checkmark icon. Floating soft holographic pie charts and data sparkles around it. Clean gradient deep navy blue background that makes the character pop inside a circular profile crop. Studio soft lighting, Octane render, 8k resolution, ultra-detailed, vibrant and professional mascot design, no text.`
  2. **สไตล์ที่ 2 (น้องแมวส้มเลขาสรุปรายงาน 3D Blind-Box Style):**
     `An adorable 3D Blind-Box / Pop Mart style chibi ginger cat character acting as a smart data report secretary, 1:1 square aspect ratio, centered avatar portrait. The cute cat is wearing round nerd glasses, a miniature navy business vest with a yellow tie, and a sleek wireless headset with a tiny microphone. It is happily holding up a neat clipboard with colorful rising analytics graphs and a golden star badge. Soft warm pastel cream and teal circular halo background, designed specifically to fit cleanly inside a round profile picture frame. Pixar and Blender 3D style, smooth clay-like vinyl texture, bright studio rim lighting, sharp focus, joyful and reliable vibe, 4k resolution, no text.`
  3. **สไตล์ที่ 3 (น้องนกฮูกมอนิเตอร์ดาต้า 24 ชม. 2D Modern Anime Vector):**
     `A vibrant 2D modern anime vector illustration of a cute smart cyber-owl mascot for a report notification bot, 1:1 square aspect ratio, centered close-up avatar composition. The little owl has bright expressive eyes behind futuristic translucent visor glasses, wearing a tiny smart blazer collar, and holding a glowing digital dashboard folder with a rising trend line and a green notification bell icon. Bold clean line art, cel-shaded vibrant colors in royal blue, energetic orange, and emerald green against a soft dark-slate background for high contrast at small icon sizes. Crisp esports/tech app mascot aesthetic, flat clean edges suitable for a circular profile icon, high resolution, no text.`

---

## 2. สิ่งที่ยังติดขัด / ยังค้างคา / ยังทำไม่สำเร็จ (Pending & Unfinished Items)

### 2.1 ช่องทางแบรนด์อื่นๆ อีก 3 แบรนด์ในระบบ 5 เพจ ที่ยังไม่ได้ใส่ Token จริง (ใน `pages.json`)
ปัจจุบันใน `messenger-engine/pages.json` เปิดช่องเตรียมไว้แล้ว แต่ **ยังไม่มีรหัสเชื่อมต่อ (Token ว่างเปล่า)** จึงยังรับ-ส่งแชทจริงไม่ได้สำหรับ 3 แบรนด์นี้ค่ะ:
1. **มิสเตอร์บุก (`brand_id: mrbuk` — Slot 2, `@305lhvvt`):**
   - มีไฟล์ข้อมูลสินค้า `config_mrbuk.json` แล้ว
   - ❌ **ยังขาด:** `line_channel_secret`, `line_channel_access_token`, `fb_page_id`, `fb_page_access_token` (ยังเป็นค่าว่าง `""` ใน `pages.json`)
2. **PADA AI (`brand_id: pada` — Slot 3, `@506xhsrj`):**
   - ❌ **ยังขาด:** Token ของ LINE OA / Facebook Page และยังใช้ `config.json` ร่วมกับข้าวบุกสุขใจอยู่ (ยังไม่ได้แยกไฟล์ `config_pada.json` เฉพาะของหลักสูตร PADA)
3. **AIFY (`brand_id: aify` — Slot 4, `@599fgktd`):**
   - ❌ **ยังขาด:** Token ของ LINE OA / Facebook Page และยังไม่มีไฟล์ `config_aify.json` เฉพาะของแบรนด์ค่ะ
4. **Instagram DM ของทุกแบรนด์:**
   - ❌ **ยังขาด:** `ig_account_id` และ `ig_access_token` ของทุกเพจยังเป็นค่าว่าง `""` ค่ะ

### 2.2 การตั้งค่าบน Meta (Facebook) และ OpenAI ที่ยังเป็นค่าเริ่มต้นใน `.env`
1. **`META_VERIFY_TOKEN=changeme` และ `META_APP_SECRET=` (ว่างเปล่า):**
   - ใน `.env` และบน Render ตอนนี้ `META_VERIFY_TOKEN` ยังเป็นค่าเริ่มต้นคำว่า `changeme` และยังไม่ได้ใส่ `META_APP_SECRET` สำหรับตรวจลายเซ็นความปลอดภัย (`X-Hub-Signature-256`) ของ Facebook Webhook ค่ะ
2. **`OPENAI_API_KEY=` (ว่างเปล่า):**
   - ตอนนี้ระบบใช้ **Google Gemini (`gemini-2.5-flash`)** เป็นสมองหลักในการตอบแชท (มี `GEMINI_API_KEY` แล้ว) ส่วน `OPENAI_API_KEY` ยังว่างอยู่ หากต้องการใช้ OpenAI เป็นตัวสำรองยามฉุกเฉินต้องนำคีย์มาเติมภายหลังค่ะ

### 2.3 เรื่องฐานข้อมูลและความเสถียรบนเซิร์ฟเวอร์ Render (Cloud Persistence & Plan)
1. **ฐานข้อมูลบน Render ยังเป็น SQLite (`DATABASE_URL=sqlite:///chatbot.db`):**
   - หากรันบน Render แพ็กเกจ Free หรือไม่มี Persistent Disk เวลาที่เซิร์ฟเวอร์ Render มีการ Deploy ใหม่ (Redeploy) หรือรีสตาร์ท ไฟล์ `.db` บนคลาวด์อาจถูกรีเซ็ตได้ (แต่กฎใน `line_group_config.json` และ `audit_lessons_learned.json` ที่ถูก Commit ลง GitHub จะไม่หายค่ะ)
   - **สิ่งที่ต้องทำต่อเมื่อพร้อม:** หากต้องการให้ประวัติแชทและฐานข้อมูลบนคลาวด์อยู่ถาวร 100% แนะนำให้เชื่อมฐานข้อมูล PostgreSQL (หรือติด Persistent Disk บนแพ็กเกจ Starter \$7/เดือน ของ Render) ค่ะ
2. **อายุของคุกกี้ JST ERP (`JST_ERP_COOKIE`):**
   - ระบบดึงยอดขายและเช็กสต็อกจาก JST ERP ใช้คุกกี้เซสชันล็อกอิน (`JST_ERP_COOKIE`) ซึ่งคุกกี้ของเว็บ JST ERP มีวันหมดอายุตามรอบของระบบ หากวันไหนบอทดึงสต็อกไม่ได้ ต้องอัปเดตค่า `JST_ERP_COOKIE` ใหม่ค่ะ
3. **ไฟล์ที่เพิ่งแก้ไขในเครื่อง รอ Commit & Push ขึ้น GitHub/Render:**
   - ไฟล์ที่เพิ่งปรับปรุงล่าสุดในเครื่อง (`app/audit.py`, `app/daily_sheet_report.py`, `app/database.py`, `app/jst_erp.py`, และโฟลเดอร์ `n8n_workflows/`) เมื่อเซสชันที่กำลังแก้ไขทำงานเสร็จสิ้นแล้ว ต้องสั่ง `git add . && git commit && git push` ทั้งไปที่ `origin` และ `render-origin` เพื่อให้เซิร์ฟเวอร์ Render อัปเดตเป็นเวอร์ชันล่าสุดค่ะ

### 2.4 การเปลี่ยนชื่อ Account และรูปโปรไฟล์จริงของบอทส่งรีพอร์ต (`workbot` @934ndvfs)
1. **ใน LINE Official Account Manager (`manager.line.biz`) ยังเป็นชื่อบริษัทเก่าอยู่:**
   - ❌ **ยังค้างคา:** บอทส่งรีพอร์ต (`@934ndvfs` Slot 5 `workbot`) ปัจจุบันยังแสดงชื่อว่า **`GENIUS POINT`** (และบอทโค้ช `@346zyzej` Slot 6 `coachbot` ยังใช้ชื่อ **`Muzart พามู`**)
   - **สิ่งที่ต้องทำต่อ:** นำรูปโปรไฟล์ตัวการ์ตูน 1:1 ที่เจนจากคำสั่งในข้อ 1.5 ไปอัปโหลดในหน้าตั้งค่าโปรไฟล์ของ `manager.line.biz` และกดเปลี่ยนชื่อ Account จาก `GENIUS POINT` เป็นชื่อกลางที่ปลอดภัย 100% (เช่น **`Daily Report Bot`** หรือ **`Buk Report Bot`**) พร้อมอัปเดตฟิลด์ `"name"` ของ Slot 5 ในไฟล์ `messenger-engine/pages.json` และ `pages.default.json` ให้ตรงกันค่ะ

### 2.5 ข้อมูลประวัติแชทที่ยังแหว่งบางช่วงเวลา และจุดที่รอตรวจทานเพิ่มเติม
1. **ช่องว่างช่วงวันที่ `20 ก.ค. – 16 ก.ย. 2026` เฉพาะของเพจหลัก `Mr.Buk มิสเตอร์บุก` (`messages page 2`):**
   - เพจ **`ข้าวบุก สุขใจ`** และเพจ **`ข้าวบุกหอมมะลิ มิสเตอร์บุก`** มีข้อมูลแชทต่อเนื่องครบทุกวัน 100% จนถึง 29 ต.ค. 2026 แล้วค่ะ
   - ❌ **สิ่งที่ยังขาด:** เฉพาะเพจหลัก **`Mr.Buk มิสเตอร์บุก`** ไฟล์ชุดเก่าตัดจบที่วันที่ `20 ก.ค. 2026` แล้วข้ามมาต่อชุดใหม่วันที่ `16 ก.ย. – 29 ต.ค. 2026` ทำให้ยังขาดไฟล์แชทช่วง **`20 ก.ค. – 16 ก.ย. 2026` (ประมาณเกือบ 2 เดือน)** ที่ยังไม่ได้ดาวน์โหลดจาก Facebook มาใส่เครื่องค่ะ (หากต้องการเก็บฐานเบอร์โทรลูกค้า `customers.csv` ของเพจหลักให้ครบทุกเดือน สามารถดาวน์โหลดเฉพาะช่วง `20 ก.ค. – 16 ก.ย. 2026` ของเพจ `Mr.Buk มิสเตอร์บุก` มาเติมภายหลังได้ค่ะ)
2. **การปรับคำตอบเรื่องอายุการเก็บรักษา (`1 ปี` vs `24 เดือน`):**
   - ใน `line_group_config.json` มีกฎใหม่จากกลุ่ม LINE เมื่อวันที่ 1 พ.ย. ให้ตอบว่า *"เก็บได้นาน 1 ปีในอุณหภูมิห้องปกติ ไม่จำเป็นต้องแช่ตู้เย็นเลยค่ะ"* ซึ่งระบบได้ปรับใน `config.json` และ `config_mrbuk.json` ให้สอดคล้องกันแล้วค่ะ (เก็บรักษาได้นาน 1 ปีในอุณหภูมิห้องปกติโดยไม่ต้องแช่ตู้เย็น)


---

## 3. การเตรียมระบบแชทบอท & ระบบสะสมแต้ม LINE OA ของ มิสเตอร์บุก (`Mr.Buk` — เตรียมเปิดใช้งานกลางเดือนพฤศจิกายน 2026)

### ✅ 3.1 สิ่งที่ทำเสร็จสมบูรณ์แล้วสำหรับ มิสเตอร์บุก (Completed)
1. **ระบบบัตรสะสมแต้มและคูปองใน LINE Official Account (`@misterbuk` / `@305lhvvt`) เปิดใช้งานจริงแล้ว:**
   - **บัตรสะสมแต้ม (`บัตรสะสมแต้ม มิสเตอร์บุก VIP`):** ลิงก์ `https://u.lin.ee/P44JSey` (สะสม 10 แต้ม / อายุบัตร 24 เดือน)
   - **กติกาการรับแต้มและของรางวัล 2 ระดับ (อัปเดตล่าสุด):**
     - **ทุกยอดสั่งซื้อ 500 บาท = รับ 1 แต้ม** (อนุโลมถุงใหญ่ 1 กก. `490.-` ร่วมรับ 1 แต้มได้ตามข้อความต้อนรับใน LINE OA)
     - **สะสมครบ 5 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิซองเล็ก `60 กรัม` จำนวน `3 ซอง` (มูลค่า 132.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
     - **สะสมครบ 10 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิถุงกลาง `500 กรัม` จำนวน `1 ถุง` (มูลค่า 249.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
   - **คูปองต้อนรับเพื่อนใหม่ VIP ลด 5% (`MRBUKVIP5`):** ลดทันที 5% ทุกโปรโมชั่นสำหรับการสั่งซื้อรอบถัดไป (1 กก. `490.-` เหลือ `465.-`, เซ็ตคู่ 41 มื้อ `950.-` เหลือ `902.-`, เซ็ต 30 ซอง `1,190.-` เหลือ `1,130.-`, เซ็ตใหญ่ 5 กก. `2,390.-` เหลือ `2,270.-`)
   - **Rich Menu (6 ปุ่ม) & ข้อความตอบกลับอัตโนมัติ (Auto-Response):** ตั้งค่าดักจับคีย์เวิร์ด `รับแต้ม`, `สะสมแต้ม`, `บัตรสะสมแต้ม`, `แลกแต้ม`, `รับสิทธิ์ลด 5%`, `ส่วนลด 5%`, `คูปองส่วนลด`, `MRBUKVIP5` ใน LINE OA Manager เรียบร้อยแล้วค่ะ
   - **ภาพ QR Code แจกแต้มแบบไม่มีวันหมดอายุ (Non-Expiring Point QR Codes):** สร้างและบันทึกไว้ที่ `D:\MrBuk Content\Mr buk line oa\` ครบ 3 ระดับ (`MrBuk_QR_Give_1pt.png` สำหรับ +1 แต้ม, `MrBuk_QR_Give_2pt.png` สำหรับ +2 แต้ม, `MrBuk_QR_Give_4pt.png` สำหรับ +4 แต้ม) พร้อมระบบกันสแกนซ้ำของ LINE OA (สแกนรับแต้มได้สูงสุดวันละ 1 ครั้งต่อ 1 บัญชี รีเซ็ตเที่ยงคืน)
   - **ไฟล์ใบแนบกล่องพัสดุ A5 สำหรับส่งโรงพิมพ์ (`D:\MrBuk print A5\300ppi\MrBuk print A5.jpg`):** ทำเสร็จเรียบร้อย แสดงทั้ง QR Code ลด 5%, วิธีทำ 4 ขั้นตอน และตารางบัตรสะสมแต้ม 10 ช่อง
2. **อัปเดตไฟล์ความรู้และกฎเหล็กเฉพาะของ มิสเตอร์บุก (`messenger-engine/config_mrbuk.json`) ครบ 100% แล้ว:**
   - แก้ไขข้อมูลใน `config_mrbuk.json` ให้เป็นข้อมูลจริงของ **มิสเตอร์บุก (`Mr.Buk`)** ทั้งหมด (ไม่ปะปนกับข้าวบุกสุขใจ): สัดส่วนแป้งบุก 46% (ผงบุกเกรดพรีเมียม 54%) + ข้าวหอมมะลิแท้ 44% + น้ำ 10%, พลังงาน 23 kcal / คาร์บ 5g, เลข อย. `13-4-06169-6-0001` + ฮาลาล, เลขบัญชีธนาคารกสิกรไทย `989-2-13624-3` (บจก. ทูเคพี อิควิปเม้นท์), ราคาจริงครบทั้ง 4 โปรโมชั่นหลัก (`44.-`, `249.-`, `490.-`, `599.-`, `1,190.-`, `950.-`, `2,390.-`), และเพิ่มบล็อก `loyalty_program` + FAQ กติกาการแอด LINE `@misterbuk` สะสมแต้มเมื่อซื้อครบ 500 บาทเรียบร้อยแล้วค่ะ
3. **โครงสร้างรองรับ `brand_id: "mrbuk"` ในโค้ดแกนกลาง (`messenger-engine`):**
   - จอง Slot 2 (`mrbuk` — `@305lhvvt`) ใน `pages.default.json` และ `pages.json` แล้ว
   - มี Endpoint `/webhook/line/mrbuk` ใน `app/main.py` แล้ว
   - ล็อกเลขบัญชีกสิกรไทย `989-2-13624-3` ใน `app/llm.py` และล็อกเลข อย. `13-4-06169-6-0001` ใน `app/audit.py` เฉพาะของ `mrbuk` เรียบร้อยแล้วค่ะ
   - มีฟังก์ชันค้นหาออเดอร์ย้อนหลังด้วยเบอร์โทร 10 หลัก (`normalize_thai_phone`) และชื่อลูกค้า (`_norm_name`) ใน `app/jst_erp.py` และ `app/parcel_tracker.py` พร้อมนำมาต่อยอดเช็กยอดสะสมแต้มได้ทันทีค่ะ

### ⚠️ 3.2 สิ่งที่ยังติด / ยังค้างคา / ยังทำไม่สำเร็จ สำหรับ มิสเตอร์บุก (Pending & Unfinished — รอทำช่วงกลางเดือน พ.ย. 2026)
1. **❌ ยังไม่ได้ใส่ Token ของ มิสเตอร์บุก (`mrbuk` — Slot 2) ใน `pages.json` / `.env`:**
   - `line_channel_secret`, `line_channel_access_token` (ของ LINE OA `@305lhvvt`), `fb_page_id`, `fb_page_access_token` (ของเพจ Facebook มิสเตอร์บุก) ยังเป็นค่าว่าง `""`
2. **❌ ยังไม่ได้เขียนโค้ดให้ `app/main.py` สลับโหลดไฟล์ `config_mrbuk.json` อัตโนมัติตาม `brand_id`:**
   - ปัจจุบัน `app/main.py` โหลด `CONFIG = load_config()` (`config.json` ของข้าวบุกสุขใจ) ตัวเดียวตอนเปิดเครื่อง ต้องปรับให้ `process_omnichannel_message` โหลด `config_mrbuk.json` เมื่อ `brand_id == "mrbuk"`
3. **❌ ยังไม่ได้ใส่รูปตารางโปรโมชั่นของ มิสเตอร์บุก และรูป QR Code แต้มสะสม (`1pt / 2pt / 4pt`) ลงใน `app/static/media/` และ `app/media_generator.py`:**
   - ปัจจุบันใน `app/static/media/` มีเฉพาะรูปโปรโมชั่นของข้าวบุกสุขใจ ต้องนำรูปโปรโมชั่นทั้ง 4 เซ็ตของมิสเตอร์บุก และไฟล์ `MrBuk_QR_Give_1pt.png`, `2pt`, `4pt` จาก `D:\MrBuk Content\Mr buk line oa\` มาใส่และแยกส่งตาม `brand_id == "mrbuk"`
4. **❌ ยังไม่ได้เขียนโมดูลเชื่อมยอดสั่งซื้อ Facebook / JST ERP เข้ากับระบบสะสมแต้ม LINE OA (`app/loyalty.py` หรือใน `database.py` + `main.py`):**
   - **ฝั่ง Facebook Messenger (เมื่อลูกค้าสั่งซื้อครบ 500 บาทขึ้นไป):** ต้องเพิ่มโค้ดให้บอทส่งข้อความชวนแอด LINE `@misterbuk` (พร้อมลิงก์ `https://u.lin.ee/P44JSey`) ท้ายการปิดการขาย (`#BUY<ยอดเงิน>`) อัตโนมัติ และจำเบอร์โทร + ยอดเงินของบิลนั้นไว้ในฐานข้อมูล
   - **ฝั่ง LINE OA `@misterbuk` (เมื่อลูกค้าแอดไลน์มาแล้วยืนยันตัวตน):** ต้องเพิ่มโค้ดรับ **เบอร์โทรศัพท์ 10 หลัก** (หรือชื่อ-นามสกุลผู้รับ) จากลูกค้าในแชท LINE แล้วนำไปค้นหายอดสั่งซื้อจริงจาก 2 แหล่ง:
     1) ตาราง `user_sessions` ใน `chatbot.db` (แชทที่เพิ่งปิดการขายทาง Facebook)
     2) API ของ `JST ERP` (`check_duplicate_order` ใน `app/jst_erp.py` ที่ดึงออเดอร์ย้อนหลังจากเบอร์โทร)
   - **ระบบป้องกันการเคลมแต้มซ้ำ & ส่ง QR แต้มอัตโนมัติ:** ต้องเพิ่มคอลัมน์ใน `chatbot.db` เพื่อผูก `phone` ➔ `line_user_id`, เก็บประวัติ `claimed_order_ids` (ป้องกันนำบิลเดิมมาขอแต้มซ้ำ), คำนวณแต้ม (`ทุก 500 บาท = 1 แต้ม`), และส่งภาพ `MrBuk_QR_Give_1pt.png` / `2pt` / `4pt` ให้ลูกค้ากดรับแต้มเข้าบัตร LINE OA ทันที
5. **❌ ยังไม่ได้ตั้งค่ารหัสร้านค้า (`JST_SHOP_ID`) และรหัสสินค้า (`SKU`) ของ มิสเตอร์บุก ใน `app/jst_erp.py`:**
   - ปัจจุบัน `app/jst_erp.py` ตั้งค่า `JST_SHOP_ID = 20759963` และรหัสสินค้า `BSJ*` ของข้าวบุกสุขใจไว้ ต้องตรวจสอบว่าในระบบ JST ERP ร้านมิสเตอร์บุกใช้ `shop_id` เดียวกันหรือแยกกัน และใช้รหัส SKU อะไรในการตัดสต็อก/เช็กออเดอร์ค่ะ
6. **❓ โจทย์กติกาธุรกิจ 3 ข้อที่รอคุณนัดฟันธงก่อนเริ่มเขียนโค้ดช่วงกลางเดือน พ.ย. 2026:**
   - **ข้อที่ 1 (การคิดแต้มต่อบิล vs สะสมยอดทบข้ามบิล):** กรณีลูกค้าสั่งเซ็ตคู่ `950 บาท` จะให้คิดแบบ **"ตัดตามบิล = รับ 1 แต้ม (หรือปัดขึ้นให้ 2 แต้ม)"** หรือให้ **"รับ 1 แต้ม แล้วเก็บเศษ 450 บาทไว้ทบกับบิลถัดไป"** ในฐานข้อมูลคะ?
   - **ข้อที่ 2 (สิทธิ์ของถุงใหญ่ 1 กก. ราคา `490 บาท`):** ยืนยันตามข้อความต้อนรับใน LINE OA ปัจจุบันเลยไหมคะว่า ถ้าลูกค้าซื้อถุงใหญ่ 1 กก. (`490.-` ซึ่งขาดอีก 10 บาทจะครบ 500) **อนุโลมให้ได้รับ 1 แต้มเต็มทันที**?
   - **ข้อที่ 3 (รูปแบบการเก็บแต้ม):** แนะนำให้ทำแบบ **Hybrid (คู่ขนาน)** คือบันทึกแต้มผูกกับเบอร์โทรไว้ในฐานข้อมูล `chatbot.db` ของบอทด้วย **พร้อมกับ** ส่งรูป QR Code ให้ลูกค้ากดสะสมในบัตร LINE Reward Card ด้วย เผื่อลูกค้าผู้สูงอายุสแกน QR ไม่เป็น บอทและแอดมินก็ยังเช็กแต้มจากเบอร์โทรให้ลูกค้าได้ 100% ค่ะ
