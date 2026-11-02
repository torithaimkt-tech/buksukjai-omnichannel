# 🧠 แกนกลางความจำระบบแชทบอท (Chatbot Core Memory & Master Status)
**อัปเดตล่าสุด:** 2 พฤศจิกายน 2026 (เวลา 10:15 น.)

เอกสารนี้คือ **แกนกลางความจำหลัก (Single Source of Truth)** ของระบบแชทบอททั้งหมดในโปรเจกต์ `D:\chat bot` เพื่อให้สามารถเปิดแชทใหม่และทำงานต่อได้ทันทีโดยไม่สูญเสียข้อมูลแม้จะลบแชทเดิมทิ้งค่ะ

---

## 1. สถาปัตยกรรมแชทบอททั้ง 4 ตัว (4-Bot Isolated Architecture)

> **กฎเหล็กการออกแบบ:**
> - **1 กลุ่ม LINE = มีบอททำงานแค่ 1 ตัวเท่านั้น** เพื่อป้องกันบอทตีกันหรือส่งรายงานผิดกลุ่ม
> - **แยกอีเมล Render แบรนด์ละ 1 อีเมล** (`buksukjai@gmail.com` แยกจาก `Tori Marketing`) เพื่อใช้โควตาฟรี `Free 750 hrs/mo` แยกกัน ไม่เสียเงิน $7/เดือน
> - **n8n ใช้แบบ Self-Hosted ฟรีไม่จำกัดโฟลว์** ภายใต้อีเมลของ `Tori Marketing` โดยแยกเป็น 4 โฟลว์อิสระสำหรับบอทแต่ละตัว (ไฟล์แม่แบบอยู่ใน [`messenger-engine/n8n_workflows/`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/))

| ลำดับ | ชื่อบอท | บทบาทหน้าที่ | LINE ID / ช่องทาง | `brand_id` ในระบบ | กลุ่ม LINE ที่ประจำการ | Webhook URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ตัวที่ 1** | **น้องบุก (Sales Bot)** | ตอบแชทขายของหน้าร้าน ดูแลลูกค้า ปิดการขาย ทวนออเดอร์ ส่ง `#BUY` | `@602xbpha` + เพจ FB ข้าวบุก สุขใจ (Channel ID: `2009665645`) | `buksukjai` | แชทส่วนตัวลูกค้า 1-on-1 (LINE OA & FB Messenger) | `https://buksukjai-omnichannel.onrender.com/webhook/line/buksukjai` และ `/webhook/facebook` |
| **ตัวที่ 2** | **บอทกลุ่มสรุปยอด (Summary & Escalation Bot)** | ส่งสรุปยอดขาย-ตัดสต็อก 07:00 น. + แจ้งเตือนเคส `[#Q...]` และส่งคำตอบกลับหาลูกค้าเมื่อแอดมินกด Reply | `GENIUS POINT` (`@934ndvfs`, Channel ID: `2009741913`) | `workbot` | กลุ่มสรุปยอด (`C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`) | `https://buksukjai-omnichannel.onrender.com/webhook/line/workbot` |
| **ตัวที่ 3** | **บอทรับคอมเมนต์สอน AI (AI Coach Bot)** | รับรูปแคปหน้าจอ + คอมเมนต์จากคุณแอมมี่และคุณนัดในกลุ่ม `Comment` เพื่ออัปเดตกฎการตอบของน้องบุกแบบถาวร (ห้ามส่งข้อความหาลูกค้าเด็ดขาด) | `Muzart พามู` (`@346zyzej`, Provider: `BukSukjai`, Channel ID: `2012318669`) | `coachbot` | กลุ่ม **`Comment (4)`** (`Cf0c8835b5b0711e80f7350ffc9af66f1`) | `https://buksukjai-omnichannel.onrender.com/webhook/line/coachbot` |
| **ตัวที่ 4** | **บอทแอดมินประสานงาน Tori Marketing** | บอทประสานงานและรับแจ้งเตือนฝั่งเอเจนซี่ Tori Marketing | รอผูก LINE OA ฝั่ง Tori Marketing | `torimarketing_admin` | กลุ่มประสานงาน Tori Marketing | โฟลว์แม่แบบ: [`4_torimarketing_admin_bot.json`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/4_torimarketing_admin_bot.json) |

*(หมายเหตุ: ค่า Channel Secret และ Channel Access Token ทั้งหมดถูกบันทึกไว้ในไฟล์ `.env` และใน Skill `buksukjai-brand-specialist` เรียบร้อยแล้วค่ะ)*

---

## 2. กฎเหล็กและคลังความรู้ที่เรียนรู้จากคุณแอมมี่ & คุณนัด (ฝังลงแกนกลางแล้ว 100%)

ข้อมูลทั้งหมดนี้ถูกบันทึกถาวรลงใน [`prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py), [`daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py), [`line_group_config.json`](file:///D:/chat%20bot/messenger-engine/line_group_config.json) และฐานข้อมูลออนไลน์บน Render เรียบร้อยแล้วค่ะ:

1. **ห้ามพิมพ์คำว่า `"ดีมากๆค่ะ"` หรือ `"ดีมากๆ เลยค่ะ"` (ตกคำว่า "ยิน"):**
   - ระบบมีตัวกรองอัตโนมัติ (Auto-Sanitizer) แปลง `"ดีมากๆ"` เป็น `"ยินดีมากๆ เลยค่ะ"` หรือ `"ด้วยความยินดีเลยค่ะ"` ทุกครั้งก่อนส่งออกหาลูกค้า (อัปเดตเพิ่มเติมจากคอมเมนต์ในกลุ่ม `Comment` เมื่อวันที่ 1 พ.ย. 2026 เวลา 21:47 น.)
2. **เวลาทวนรายการสั่งซื้อ ไม่ต้องให้ลูกค้าพิมพ์ยืนยันซ้ำ (อัปเดตจากกลุ่ม `Comment` วันที่ 2 พ.ย. 2026 เวลา 08:02 น.):**
   - เมื่อลูกค้าแจ้งขนาด + ชื่อที่อยู่เบอร์โทร + เลือกเก็บเงินปลายทางหรือส่งสลิปโอนเงินครบถ้วนแล้ว **เวลาทวนรายการสั่งซื้อไม่ต้องให้ลูกค้าพิมพ์คำว่า `"ยืนยัน"` ซ้ำอีก** ให้กล่าวขอบคุณที่สั่งซื้อและแจ้งเตรียมจัดส่งได้เลยทันที พร้อมส่ง `#BUY<ยอดเงิน>` แยกกล่องเดี่ยว และห้ามส่งรูปโปรโมชั่นซ้ำตอนทวนออเดอร์
3. **น้ำเสียงอบอุ่น นุ่มนวล ใส่ใจความรู้สึก:**
   - อ่านบริบทและอารมณ์ของลูกค้าให้แตกฉาน ตอบคำถามให้ตรงประเด็นก่อนด้วยความเข้าใจ ไม่ตัดบทห้วนๆ
4. **เรทราคาส่ง 100 ถุง (คละขนาดไม่ได้ / ไม่รวมค่าจัดส่ง):**
   - ขนาด **60 กรัม** จำนวน 100 ถุง = **ถุงละ 25 บาท**
   - ขนาด **500 กรัม** จำนวน 100 ถุง = **ถุงละ 165 บาท**
   - ขนาด **1 กิโลกรัม** จำนวน 100 ถุง = **ถุงละ 290 บาท**
   - หากลูกค้าต้องการสั่งมากกว่า 100 ถุง หรือต้องการใบเสนอราคา ให้ขอชื่อและเบอร์โทรเพื่อให้แอดมินติดต่อกลับค่ะ
5. **อายุการเก็บรักษา (Shelf Life):**
   - ข้าวบุกสุขใจเก็บได้นาน **1 ปี** ในอุณหภูมิห้องปกติ (เก็บในที่แห้งและพ้นแสงแดด ไม่ต้องแช่ตู้เย็นค่ะ)
6. **ระบบหยุดบอทชั่วคราวเมื่อเจอคำถามนอกสคริปต์ (Smart Escalation):**
   - หากลูกค้าถามคำถามแปลกใหม่ที่ AI ไม่มั่นใจ บอทจะตอบรับลูกค้าอย่างสุภาพ พักบอทเฉพาะแชทนั้น (`pause_Session_for_admin_review`) และส่งแจ้งเตือน `[#Q...]` เข้ากลุ่มสรุปยอดทันที

---

## 3. สรุปสถานะงานทั้งหมด: สิ่งที่ทำเสร็จแล้ว vs สิ่งที่ยังค้างคา

### ✅ ก. สิ่งที่ทำเสร็จสมบูรณ์และใช้งานได้จริงแล้ว (Completed & Working 100%)

1. **แยกบอทรับคอมเมนต์ (`@346zyzej` Muzart พามู) เข้ากลุ่ม `Comment (4)` สำเร็จและทำงานจริงตอนปิดคอมพิวเตอร์:**
   - ทดสอบจริงเมื่อคืนวันที่ 1 พ.ย. (21:47 น.) และเช้าวันที่ 2 พ.ย. (08:02 น.) ขณะปิดคอมพิวเตอร์ บอท `@346zyzej` อ่านรูปแคปหน้าจอ + ข้อความสอนงานจากคุณแอมมี่และคุณนัด ตอบกลับภายใน 2 วินาที และบันทึกกฎใหม่ลงสมองกลออนไลน์ทันที
2. **ล็อกระบบนิรภัยกลุ่มสรุปยอด (`@934ndvfs` GENIUS POINT) และแยกกลุ่มส่งรายงาน 07:00 น. สำเร็จ:**
   - เช้าวันที่ 2 พ.ย. เวลา `07:00:51 น.` ระบบส่งสรุปยอดขายประจำวัน (`2026-11-01`) และตัดสต็อกเข้าเฉพาะกลุ่มสรุปยอด (`C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`) โดย **ไม่ส่งเข้ากลุ่ม `Comment (4)`**
   - ป้องกันบอทหยิบข้อความคุยเล่นในกลุ่มไปส่งให้ลูกค้า 100% (จะส่งหาลูกค้าเฉพาะเมื่อกด Reply ที่ข้อความ `[#Q...]` หรือพิมพ์ขึ้นต้นด้วย `#Q1` / `ตอบ:` เท่านั้น)
3. **ฝังกฎทั้งหมดลงในโค้ดแกนกลาง (`D:\chat bot\messenger-engine`) เรียบร้อยครบทุกไฟล์:**
   - อัปเดตทั้ง [`prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py), [`llm.py`](file:///D:/chat%20bot/messenger-engine/app/llm.py), [`audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py), [`daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py), และ [`line_group_config.json`](file:///D:/chat%20bot/messenger-engine/line_group_config.json)
4. **สร้างไฟล์แม่แบบ n8n แยก 4 แชทบอทเสร็จสมบูรณ์:**
   - อยู่ในโฟลเดอร์ [`D:\chat bot\messenger-engine\n8n_workflows\`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/) ทั้ง 4 ไฟล์ (`1_buksukjai_sales_bot.json`, `2_buksukjai_summary_bot.json`, `3_buksukjai_ai_coach_bot.json`, `4_torimarketing_admin_bot.json`)
5. **เปิดบัญชี Render ฟรีแยกภายใต้อีเมล `buksukjai@gmail.com` (`Bukrice's workspace`) และอัปโหลดโค้ดขึ้น GitHub `pordiporditeam-sudo/buksukjai-omnichannel` เรียบร้อยแล้ว**

---

### ⚠️ ข. สิ่งที่ยังติด / ยังค้างคา / ยังทำไม่สำเร็จ (Pending / Unfinished Items)

1. **การย้ายเซิร์ฟเวอร์ Render มาอยู่บนบัญชี `buksukjai@gmail.com` เต็มตัว (หรืออัปเดต GitHub ฝั่งที่เชื่อมกับ Render ตัวปัจจุบัน):**
   - **สิ่งที่ยังค้าง:** บัญชี Render ใหม่ของ `buksukjai@gmail.com` (`Bukrice's workspace`) เปิดเสร็จแล้ว แต่ยังไม่ได้กดเชื่อมกับ GitHub (`pordiporditeam-sudo/buksukjai-omnichannel`) เพื่อสร้าง Web Service ตัวใหม่ ส่วนเซิร์ฟเวอร์ตัวที่กำลังออนไลน์อยู่ตอนนี้ (`https://buksukjai-omnichannel.onrender.com`) ยังผูกอยู่กับ GitHub บัญชีเดิม (`torithaimkt-tech/buksukjai-omnichannel` ที่ Commit `ab74985`)
   - **ผลกระทบเล็กน้อย:** เวลาเชิญบอท `@346zyzej` เข้ากลุ่มใหม่ ข้อความต้อนรับแรกสุดยังใช้ข้อความของรุ่นก่อนหน้า (แต่ระบบรับรูปแคปหน้าจอ + สอนบอทในกลุ่ม `Comment` ทำงานได้ 100% และกฎที่สอนผ่านกลุ่ม `Comment` ถูกบันทึกบนเซิร์ฟเวอร์ออนไลน์เรียบร้อยแล้วค่ะ)
   - **วิธีทำต่อในแชทหน้า:** กดเชื่อม GitHub `pordiporditeam-sudo/buksukjai-omnichannel` เข้ากับ Render ของ `buksukjai@gmail.com` (หรือ Push โค้ดล่าสุดเข้า `torithaimkt-tech/buksukjai-omnichannel`) เพื่อให้โค้ดแกนกลางชุดล่าสุดขึ้น Cloud 100%
2. **การนำไฟล์ Workflow ทั้ง 4 ตัว ไปกด Import เข้าหน้ากระดาน n8n จริง (ภายใต้อีเมล `Tori Marketing`):**
   - **สิ่งที่ยังค้าง:** สร้างไฟล์ JSON แม่แบบแยก 4 แชทบอทไว้ในเครื่องเรียบร้อยแล้ว แต่ยังไม่ได้เปิดระบบ n8n Self-Hosted ของอีเมล `Tori Marketing` เพื่อกด Import ไฟล์ทั้ง 4 ตัวขึ้นหน้ากระดานจริง
   - **วิธีทำต่อในแชทหน้า:** เปิดหน้าเว็บ n8n ของ `Tori Marketing` แล้วกด `Import from File` เลือกไฟล์ทั้ง 4 ตัวจาก [`D:\chat bot\messenger-engine\n8n_workflows\`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/)
3. **การผูก LINE OA และตั้งค่าบอทตัวที่ 4 (บอทแอดมินประสานงานฝั่ง `Tori Marketing`):**
   - **สิ่งที่ยังค้าง:** โฟลว์ที่ 4 (`4_torimarketing_admin_bot.json`) เตรียมโครงสร้างแยกไว้แล้ว แต่ยังไม่ได้ใส่ Channel Secret / Access Token ของ LINE OA ฝั่ง Tori Marketing และยังไม่ได้กำหนดรายละเอียดคำสั่งประสานงานเฉพาะของทีมเอเจนซี่ค่ะ
