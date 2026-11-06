# 🧠 แกนกลางความจำระบบแชทบอท (Chatbot Core Memory & Master Status)
**อัปเดตล่าสุด:** 6 พฤศจิกายน 2026 (เวลา 17:50 น.)

เอกสารนี้คือ **แกนกลางความจำหลัก (Single Source of Truth)** ของระบบแชทบอททั้งหมดในโปรเจกต์ `D:\chat bot` (และ [`messenger-engine/CORE_SYSTEM_MEMORY.md`](file:///D:/chat%20bot/messenger-engine/CORE_SYSTEM_MEMORY.md)) เพื่อให้สามารถเปิดแชทใหม่และทำงานต่อได้ทันทีโดยไม่สูญเสียข้อมูลแม้จะลบแชทเดิมทิ้งค่ะ

---

## 1. สถาปัตยกรรมแชทบอททั้ง 4 ตัว (4-Bot Isolated Architecture)

> **กฎเหล็กการออกแบบ:**
> - **1 กลุ่ม LINE = มีบอททำงานแค่ 1 ตัวเท่านั้น** เพื่อป้องกันบอทตีกันหรือส่งรายงานผิดกลุ่ม
> - **แยกอีเมล Render แบรนด์ละ 1 อีเมล** (`buksukjai@gmail.com` แยกจาก `Tori Marketing`) เพื่อใช้โควตาฟรี `Free 750 hrs/mo` แยกกัน ไม่เสียเงิน \$7/เดือน
> - **n8n ใช้แบบ Self-Hosted ฟรีไม่จำกัดโฟลว์** ภายใต้อีเมลของ `Tori Marketing` โดยแยกเป็น 4 โฟลว์อิสระสำหรับบอทแต่ละตัว (ไฟล์แม่แบบอยู่ใน [`messenger-engine/n8n_workflows/`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/))

| ลำดับ | ชื่อบอท | บทบาทหน้าที่ | LINE ID / ช่องทาง | `brand_id` ในระบบ | กลุ่ม LINE ที่ประจำการ | Webhook URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ตัวที่ 1** | **น้องบุก (Sales Bot)** | ตอบแชทขายของหน้าร้าน ดูแลลูกค้า ปิดการขาย ทวนออเดอร์ ส่ง `#BUY` ขุดแชท และแจ้งเลขพัสดุ | `@602xbpha` + เพจ FB ข้าวบุก สุขใจ (`806129109240845`, LINE Channel ID: `2009665645`) | `buksukjai` | แชทส่วนตัวลูกค้า 1-on-1 (LINE OA & FB Messenger) | `https://buksukjai-omnichannel.onrender.com/webhook/line/buksukjai` และ `/webhook/facebook` |
| **ตัวที่ 2** | **บอทกลุ่มสรุปยอด (Summary & Escalation Bot)** | ส่งสรุปยอดขาย-ตัดสต็อก 07:00 น. + แจ้งเตือนเคส `[#Q...]` และส่งคำตอบกลับหาลูกค้าเมื่อแอดมินกด Reply | `GENIUS POINT` (`@934ndvfs`, Channel ID: `2009741913`) | `workbot` | กลุ่มสรุปยอด (`C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`) | `https://buksukjai-omnichannel.onrender.com/webhook/line/workbot` |
| **ตัวที่ 3** | **บอทรับคอมเมนต์สอน AI (AI Coach Bot)** | รับรูปแคปหน้าจอ + คอมเมนต์จากคุณแอมมี่และคุณนัดในกลุ่ม `Comment` เพื่ออัปเดตกฎการตอบของน้องบุกแบบถาวร (ห้ามส่งข้อความหาลูกค้าเด็ดขาด) | `Muzart พามู` (`@346zyzej`, Provider: `BukSukjai`, Channel ID: `2012318669`) | `coachbot` | กลุ่ม **`Comment (4)`** (`Cf0c8835b5b0711e80f7350ffc9af66f1`) | `https://buksukjai-omnichannel.onrender.com/webhook/line/coachbot` |
| **ตัวที่ 4** | **บอทแอดมินประสานงาน Tori Marketing** | บอทประสานงานและรับแจ้งเตือนฝั่งเอเจนซี่ Tori Marketing | รอผูก LINE OA ฝั่ง Tori Marketing | `torimarketing_admin` | กลุ่มประสานงาน Tori Marketing | โฟลว์แม่แบบ: [`4_torimarketing_admin_bot.json`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/4_torimarketing_admin_bot.json) |

*(หมายเหตุ: ค่า Channel Secret และ Channel Access Token ทั้งหมดถูกบันทึกไว้ในไฟล์ `.env`, `config_loader.py` และใน Skill `buksukjai-brand-specialist` เรียบร้อยแล้วค่ะ)*

---

## 2. กฎเหล็กและคลังความรู้ที่เรียนรู้จากคุณแอมมี่ & คุณนัด (ฝังลงแกนกลางแล้ว 100%)

ข้อมูลทั้งหมดนี้ถูกบันทึกถาวรลงใน [`prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py), [`llm.py`](file:///D:/chat%20bot/messenger-engine/app/llm.py), [`audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py), [`daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py), [`line_group_config.json`](file:///D:/chat%20bot/messenger-engine/line_group_config.json), [`audit_lessons_learned.json`](file:///D:/chat%20bot/messenger-engine/audit_lessons_learned.json) และฐานข้อมูลออนไลน์บน Render เรียบร้อยแล้วค่ะ:

1. **ห้ามพิมพ์คำว่า `"ดีมากๆค่ะ"` หรือ `"ดีมากๆ เลยค่ะ"` (ตกคำว่า "ยิน" — เคสคุณ `Gus Sasi`):**
   - ระบบมีตัวกรองอัตโนมัติ (Auto-Sanitizer) ใน [`clean_chat_text()`](file:///D:/chat%20bot/messenger-engine/app/llm.py#L57-L97) และ [`audit_outgoing_reply()`](file:///D:/chat%20bot/messenger-engine/app/audit.py#L201-L238) แปลง `"ดีมากๆค่ะขอบพระคุณมากๆนะคะ"` หรือ `"ดีมากๆ"` เป็นประโยคเต็ม `"ด้วยความยินดีเลยค่ะ 😊 ขอบพระคุณที่ไว้วางใจให้ข้าวบุกสุขใจดูแลมื้ออร่อยนะคะ 💚🙏"` หรือ `"ยินดีมากๆ เลยค่ะ"` พร้อมเว้นวรรคให้สวยงามทุกครั้งก่อนส่งออกหาลูกค้า (และล็อกแชทคุณ `Gus Sasi` เป็น `completed` ติดดาว `⭐` ไม่ส่งข้อความซ้ำไปรบกวนลูกค้าคนเดิม)
2. **เวลาทวนรายการสั่งซื้อ ไม่ต้องให้ลูกค้าพิมพ์ยืนยันซ้ำ (เคสคุณโชกุน `Jt Shogun Tj` — อัปเดตจากกลุ่ม `Comment` วันที่ 2 พ.ย. 2026 เวลา 08:02 น.):**
   - เมื่อลูกค้าแจ้งขนาด + ชื่อที่อยู่เบอร์โทร + เลือกเก็บเงินปลายทางหรือส่งสลิปโอนเงินครบถ้วนแล้ว **เวลาทวนรายการสั่งซื้อไม่ต้องให้ลูกค้าพิมพ์คำว่า `"ยืนยัน"` ซ้ำอีก** ให้กล่าวขอบคุณที่สั่งซื้อและแจ้งเตรียมจัดส่งได้เลยทันที พร้อมส่ง `#BUY<ยอดเงิน>` แยกกล่องเดี่ยว และห้ามส่งรูปโปรโมชั่นซ้ำตอนทวนออเดอร์
3. **แยกกล่องข้อความ `#BUY<ยอดเงิน>` เดี่ยว 100% (สำหรับ ROI Tracking ของคุณแอมมี่):**
   - บังคับแยก `#BUY459`, `#BUY499`, `#BUY899`, `#BUY939` ฯลฯ ออกเป็น **1 กล่องข้อความเดี่ยว (`#BUY...` ล้วนๆ ห้ามปนกับข้อความอื่น)**
4. **น้ำเสียงอบอุ่น นุ่มนวล ใส่ใจความรู้สึก:**
   - อ่านบริบทและอารมณ์ของลูกค้าให้แตกฉาน ตอบคำถามให้ตรงประเด็นก่อนด้วยความเข้าใจ ไม่ตัดบทห้วนๆ
5. **เรทราคาส่ง 100 ถุง (คละขนาดไม่ได้ / ไม่รวมค่าจัดส่ง):**
   - ขนาด **60 กรัม** จำนวน 100 ถุง = **ถุงละ 25 บาท** (2,500 บาท)
   - ขนาด **500 กรัม** จำนวน 100 ถุง = **ถุงละ 165 บาท** (16,500 บาท)
   - ขนาด **1 กิโลกรัม** จำนวน 100 ถุง = **ถุงละ 290 บาท** (29,000 บาท)
   - หากลูกค้าต้องการสั่งมากกว่า 100 ถุง หรือต้องการใบเสนอราคา ให้ขอชื่อและเบอร์โทรเพื่อให้แอดมินติดต่อกลับค่ะ
6. **อายุการเก็บรักษา (Shelf Life):**
   - ข้าวบุกสุขใจเก็บได้นาน **1 ปี** ในอุณหภูมิห้องปกติ (เก็บในที่แห้งและพ้นแสงแดด ไม่ต้องแช่ตู้เย็นค่ะ)
   - มิสเตอร์บุกเก็บได้นาน **2 ปี** ในอุณหภูมิห้องปกติ (ไม่ต้องแช่ตู้เย็นค่ะ)
7. **ลิงก์สั่งซื้อ Shopee & TikTok Shop ของข้าวบุกสุขใจ (อัปเดตจากกลุ่ม `Comment`):**
   - **Shopee:** `https://s.shopee.co.th/7KvbzDtoOv`
   - **TikTok Shop:** `https://vt.tiktok.com/ZSXtHF2kT/?page=TikTokShop`
   - มีด่านตรวจอัตโนมัติใน [`audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py) แนบลิงก์ทั้ง 2 ช่องทางทันทีหากลูกค้าถามหา Shopee/TikTok หรือขอลิงก์สั่งซื้อค่ะ
8. **ระบบแยกสคริปต์และคลังความรู้ทั้ง 4 แบรนด์ 100% (`buksukjai`, `mrbuk`, `pada`, `aify`) + สมองสำรองอัตโนมัติ (`OPENAI_API_KEY`):**
   - โหลดไฟล์ `config.json`, `config_mrbuk.json`, `config_pada.json`, `config_aify.json` แยกตาม `brand_id` อัตโนมัติใน [`prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py), [`llm.py`](file:///D:/chat%20bot/messenger-engine/app/llm.py), และ [`audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py)
   - รองรับการสลับไปใช้ `OPENAI_API_KEY` (`gpt-4o-mini`) อัตโนมัติทันทีหาก `GEMINI_API_KEY` ขัดข้อง
9. **ระบบหยุดบอทชั่วคราวเมื่อเจอคำถามนอกสคริปต์ (Smart Escalation):**
   - หากลูกค้าถามคำถามแปลกใหม่ที่ AI ไม่มั่นใจ บอทจะตอบรับลูกค้าอย่างสุภาพ พักบอทเฉพาะแชทนั้น (`pause_session_for_admin_review`) และส่งแจ้งเตือน `[#Q...]` เข้ากลุ่มสรุปยอดทันที

---

## 3. สรุปสถานะงานทั้งหมด: สิ่งที่ทำเสร็จแล้ว vs สิ่งที่ยังติด/ยังค้างคา

### ✅ ก. สิ่งที่ทำเสร็จสมบูรณ์และใช้งานได้จริงแล้ว (Completed & Working 100%)

1. **ระบบตอบแชทลูกค้าอัตโนมัติ 24 ชม. บน Cloud (`Render`) แม้ปิดคอมพิวเตอร์:**
   - มี `Keep-Alive` ยิง `/health` ทุก 60 วินาที และ `Active Facebook Graph API Auto-Responder` ([`followup.py`](file:///D:/chat%20bot/messenger-engine/app/followup.py#L728-L854)) ดึงแชทจาก Facebook Page มาตอบอัตโนมัติทุก 60 วินาที
   - ป้องกันข้อความจากบอทเบื้องหลังไปอัปเดต `last_interaction_time` ใน [`database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py#L158-L170) ทำให้แชทเก่าไม่ถูกดึงกลับมาเป็นแชทใหม่
2. **แยกบอทรับคอมเมนต์ (`@346zyzej` Muzart พามู) เข้ากลุ่ม `Comment (4)` สำเร็จและทำงานจริงตอนปิดคอมพิวเตอร์:**
   - ทดสอบจริงเมื่อคืนวันที่ 1 พ.ย. (21:47 น.) และเช้าวันที่ 2 พ.ย. (08:02 น.) ขณะปิดคอมพิวเตอร์ บอท `@346zyzej` อ่านรูปแคปหน้าจอ + ข้อความสอนงานจากคุณแอมมี่และคุณนัด ตอบกลับภายใน 2 วินาที และบันทึกกฎใหม่ลงสมองกลออนไลน์ทันที
3. **ล็อกระบบนิรภัยกลุ่มสรุปยอด (`@934ndvfs` GENIUS POINT) และแยกกลุ่มส่งรายงาน 07:00 น. สำเร็จ:**
   - สรุปยอดขายลง Google Sheets (`1mMO_aZnaCaDskrJMreJiaonFqna-WNKBhOoozAWxIhE`) เวลา `01:00 น.` และส่งสรุปยอดขาย + ตัดสต็อก + **ยอดสต็อกคงเหลือในคลังล่าสุด** เวลา `07:00 น.` เข้าเฉพาะกลุ่มสรุปยอด (`C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`) โดย **ไม่ส่งเข้ากลุ่ม `Comment (4)`**
   - ป้องกันบอทหยิบข้อความคุยเล่นในกลุ่มไปส่งให้ลูกค้า 100% (จะส่งหาลูกค้าเฉพาะเมื่อกด Reply ที่ข้อความ `[#Q...]` หรือพิมพ์ขึ้นต้นด้วย `#Q1` / `ตอบ:` เท่านั้น)
4. **แก้ไขบอทขุดแชทลูกค้าที่เงียบหายไป (3-Stage Ghost Re-engagement Bot — [`followup.py`](file:///D:/chat%20bot/messenger-engine/app/followup.py#L174-L420)):**
   - ตรวจจับ Stage จากข้อความจริงในแชท (`detect_reengage_stage_from_text`) ป้องกันการส่งข้อความขุดซ้ำเมื่อเซิร์ฟเวอร์รีสตาร์ท
   - บังคับระยะห่างขั้นต่ำ (`Stage 1 >= 1 ชม.`, `Stage 2 ห่างจาก Stage 1 >= 5 ชม.`, `Stage 3 ห่างจาก Stage 2 >= 12 ชม.`)
   - บล็อกการขุดแชทสำหรับลูกค้าที่แจ้งเบอร์โทร 10 หลัก หรือที่อยู่จัดส่งแล้ว (เช่น เคสคุณ `Sam Siri`)
   - สุ่มชุดข้อความหลากหลายแพทเทิร์น (สั้น 1 กล่อง / กลาง 1 กล่อง / ยาว 2 กล่อง) ไม่ซ้ำแพทเทิร์นเดิม
5. **แก้ไขระบบแจ้งเตือนเลขพัสดุ 2 จังหวะให้ต่างกันชัดเจน ([`parcel_tracker.py`](file:///D:/chat%20bot/messenger-engine/app/parcel_tracker.py)):**
   - **จังหวะที่ 1 (ส่งแล้ว):** ส่ง **2 กล่องข้อความ** (การ์ดแจ้งขนส่ง `J&T Express` + เลขพัสดุ และข้อความอุ่นใจว่าจะคอยตามพัสดุให้)
   - **จังหวะที่ 2 (ถึงแล้ว):** ส่ง **1 กล่องข้อความสั้นกระชับ** (ขึ้นต้นด้วย `✅` / `🎉` แจ้งเวลาที่จัดส่งถึงมือเรียบร้อย โดยไม่ซ้ำบล็อกเลขพัสดุเดิม)
6. **แก้ไขปัญหาออเดอร์ใน JST ERP ขึ้น `ผิดปกติ (ยังไม่ตั้งค่าการขนส่ง)` ([`jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py#L552-L689)):**
   - ผูกขนส่ง **J&T Express (`ExpressId: 219956`)** และกดอนุมัติ (`Audit`) ให้กับออเดอร์ที่ตกค้างเรียบร้อยแล้ว (`#233281 ปาจรีย์`, `#233279 Chanasiri Amp`, `#233275 กัส ศศิยาพัชร์`) และเพิ่มระบบ `auto_fix_missing_express_orders()` รันตรวจสอบอัตโนมัติทุก 10 นาทีควบคู่กับระบบตรวจสลิป (`verify_and_auto_confirm_jst_slips`)
7. **สร้างไฟล์แม่แบบ n8n แยก 4 แชทบอทเสร็จสมบูรณ์:**
   - อยู่ในโฟลเดอร์ [`D:\chat bot\messenger-engine\n8n_workflows\`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/) ทั้ง 4 ไฟล์ (`1_buksukjai_sales_bot.json`, `2_buksukjai_summary_bot.json`, `3_buksukjai_ai_coach_bot.json`, `4_torimarketing_admin_bot.json`)

---

### ⚠️ ข. สิ่งที่ยังติด / ยังค้างคา / ยังทำไม่สำเร็จ (แยกตามกลุ่มงานชัดเจน สำหรับส่งต่อในแต่ละแชท)

#### 💬 หมวดที่ 1: งานของ "กลุ่มคอมเมนต์ / พัฒนาการตอบแชทลูกค้า" (บอทน้องบุก `@602xbpha` & บอท AI Coach `@346zyzej`)
1. **อัปเดตกฎการตอบแชทและสำนวนชุดล่าสุดขึ้นเซิร์ฟเวอร์ Cloud ให้ครบ 100%:**
   - กฎทวนออเดอร์ (ทั้งเก็บปลายทางและโอนเงิน) **ไม่ต้องให้ลูกค้าพิมพ์คำว่า `"ยืนยัน"` ซ้ำ** และ **ห้ามส่งรูปโปรโมชั่นซ้ำตอนทวนออเดอร์** (เคสคุณโชกุน `Jt Shogun Tj`)
   - กฎตรวจคำตอบรับคำขอบคุณ **ห้ามตกคำว่า `"ยิน"`** เช่น `"ดีมากๆค่ะ..."` ให้แปลงเป็น `"ด้วยความยินดีเลยค่ะ..."` เสมอ (เคสคุณ `Gus Sasi`)
   - ระบบสุ่มข้อความบอทขุดแชท 3 จังหวะ (สั้น 1 กล่อง / กลาง 1 กล่อง / ยาว 2 กล่อง) และบล็อกการขุดแชทลูกค้าที่ส่งเบอร์โทร 10 หลักหรือที่อยู่แล้ว (เคสคุณ `Sam Siri`)
   - ระบบแจ้งเลขพัสดุ 2 จังหวะที่แยกแพทเทิร์นสั้น-ยาวชัดเจน (จังหวะส่งแล้ว 2 กล่อง vs จังหวะถึงมือแล้ว 1 กล่องสั้นกระชับ)
2. **การสอนบอทเพิ่มเติมจากเคสจริงในกลุ่ม `Comment (4)` (`Cf0c8835b5b0711e80f7350ffc9af66f1`) และการอัปเดตเลข อย. เมื่อได้รับอนุมัติจริง:**
   - รับรูปแคปหน้าจอและคอมเมนต์ติชมจากคุณแอมมี่/คุณนัดผ่านบอท `@346zyzej` เพื่อปรับปรุงสำนวนการตอบแชทอย่างต่อเนื่อง
   - เมื่อได้รับเลข อย. จริงของข้าวบุกสุขใจแล้ว จึงนำมาอัปเดตใน `config.json` (ปัจจุบันล็อกกฎห้ามเปิดประเด็นเรื่อง อย. เอง และห้ามแจ้งเลขปลอมเด็ดขาด)

---

#### 📊 หมวดที่ 2: งานของ "กลุ่มสรุปยอด / สต็อกคลัง / ระบบออเดอร์ JST ERP" (บอทกลุ่มสรุปยอด `GENIUS POINT @934ndvfs`)
1. **การเปิดระบบคีย์ออเดอร์จาก Facebook เข้า JST ERP อัตโนมัติ (`AUTO_SYNC_ENABLED`):**
   - ปัจจุบันใน [`jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py#L74) ปิด `AUTO_SYNC_ENABLED = False` ไว้ชั่วคราว เพื่อไม่ให้คีย์ชนกับแอดมินคนตอนกลางคืน (หลังจากเกิดเคสออเดอร์ซ้ำเมื่อวันที่ 31 ต.ค. 3 รายการ: `ครูเล็ก #233258/#232992`, `โยษิตา #233253/#232993`, `สุกัญญา #233251/#232994`)
   - **สิ่งที่ต้องทำต่อในกลุ่มสรุปยอด:**
     - ตรวจสอบและเคลียร์สถานะออเดอร์ซ้ำของวันที่ 31 ต.ค. ในระบบ JST ERP
     - เมื่อตกลงให้ AI คีย์ออเดอร์แทนแอดมินคน 100% (แอดมินหยุดคีย์มือ) ให้สลับ `AUTO_SYNC_ENABLED = True` เพื่อให้บอทคีย์ออเดอร์รอบ 06:00 น. + ผูกขนส่ง J&T Express (`219956`) + กดอนุมัติ (`Audit`) เข้าคลังอัตโนมัติก่อนส่งสรุปยอด 07:00 น.
2. **การดูแลอายุ Session Cookie ของระบบ JST ERP (`DEFAULT_JST_COOKIE`):**
   - ระบบดึงยอดขายรายวัน, ดึงสต็อกคงเหลือ (`60g`, `500g`, `1kg`), ตรวจสลิปอัตโนมัติ และผูกขนส่ง J&T ทำงานผ่าน Cookie ของเว็บ `asia-web.jsterp.com` (มีอายุประมาณ 7–14 วัน)
   - **สิ่งที่ต้องทำต่อในกลุ่มสรุปยอด:** เพิ่มระบบแจ้งเตือนเข้ากลุ่มสรุปยอดทันทีหาก Cookie ของ JST ERP หมดอายุ เพื่อให้อัปเดต Cookie ใหม่ได้ทันก่อนรอบสรุปยอด 01:00 น. และ 07:00 น.
3. **การตรวจสอบความตรงกันของยอดขาย 3 ทาง (JST ERP vs Google Sheets vs แฮชแท็ก `#BUY` ใน ROI Tracking):**
   - อัปเดตโค้ดชุดตัดออเดอร์ซ้ำ (`jst_duplicates_removed` ใน [`daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py)) ขึ้นเซิร์ฟเวอร์ Cloud เพื่อให้รายงาน 07:00 น. และ Google Sheets นับเฉพาะใบหลักเพียงใบเดียวเสมอ

---

#### 🛠️ หมวดที่ 3: งานส่วนอื่นๆ (โครงสร้างพื้นฐาน Cloud / n8n / แบรนด์อื่น — แยกออกจากกลุ่มคอมเมนต์และกลุ่มสรุปยอด)
1. **✅ อัปเกรดระบบฐานข้อมูลถาวร (PostgreSQL + Persistent Snapshot Auto-Restore) & Render Blueprint เสร็จแล้ว 100%:**
   - อัปเกรด [`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py) ให้รองรับทั้ง **PostgreSQL (`postgresql+psycopg2://` / `postgres://`)** และ **SQLite + ระบบสำรองข้อมูลอัตโนมัติ (`db_persistent_snapshot.json`)** ที่กู้คืนประวัติแชท LINE OA และแต้มสะสม `LoyaltyMember` / `LoyaltyClaimedOrder` อัตโนมัติทุกครั้งที่เซิร์ฟเวอร์เริ่มทำงานใหม่ (ข้อมูลไม่หายแม้มีการ Redeploy บน Render)
   - อัปเดต [`render.yaml`](file:///D:/chat%20bot/render.yaml) ให้ตั้งค่า `plan: free` พร้อมประกาศฐานข้อมูล `buksukjai-db` (`PostgreSQL Free`, โซน `singapore`) และเตรียมโค้ดแกนกลางชุดล่าสุดสำหรับ `torithaimkt-tech/buksukjai-omnichannel` เรียบร้อยแล้วค่ะ
2. **✅ นำเข้าไฟล์ Workflow ทั้ง 4 ตัวขึ้นระบบกระดาน `BaanTori` & เตรียมสคริปต์รัน `n8n` Self-Hosted เสร็จแล้ว 100%:**
   - ซิงก์ไฟล์ทั้ง 4 โฟลว์จาก [`messenger-engine/n8n_workflows/`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/) ไปยัง [`D:\torimarketing\n8n-workflows\`](file:///D:/torimarketing/n8n-workflows/) และนำเข้าขึ้นกระดาน `BaanTori` (`http://localhost:3000` / `data/amp_ads_config.json`) พร้อมสคริปต์คลิกเดียว [`import_and_start_n8n.bat`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/import_and_start_n8n.bat) และ API `/api/n8n/workflows`
3. **✅ ผูก LINE OA บอทตัวที่ 4 (`AIFY @599fgktd` สำหรับแอดมินประสานงาน `Tori Marketing`) และเตรียมไฟล์ข้อมูลสินค้าครบทั้ง 4 แบรนด์แล้ว:**
   - ผูก `LINE Channel ID: 2012318539`, `Channel Secret: 2e841449fe0466ebba1abcf68953966b`, และ `Access Token` ของ **`AIFY (@599fgktd)`** ลงใน [`4_torimarketing_admin_bot.json`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/4_torimarketing_admin_bot.json) พร้อมตรรกะตรวจจับรหัสกลุ่ม (`C...`) และคำสั่งประสานงาน (`สรุปงาน`, `เช็กสถานะ`, `รหัสกลุ่ม`, `#งานด่วน`) แยกขาดจากข้าวบุกสุขใจ 100%
   - สร้างและผูกไฟล์ [`config_mrbuk.json`](file:///D:/chat%20bot/messenger-engine/config_mrbuk.json), [`config_pada.json`](file:///D:/chat%20bot/messenger-engine/config_pada.json), และ [`config_aify.json`](file:///D:/chat%20bot/messenger-engine/config_aify.json) เสร็จครบถ้วน (ส่วนสล็อต `mrbuk`, `pada`, `aify` ใน `buksukjai-omnichannel` ตั้ง `active: false` ไว้เพื่อป้องกันข้อความทดสอบหลุดเข้ากลุ่ม `BUK TEAM` จนกว่าจะนำ Token จริงของ `mrbuk` และ `pada` มาเปิดใช้งานค่ะ)


---

## 4. การเตรียมระบบแชทบอท & ระบบสะสมแต้ม LINE OA ของ มิสเตอร์บุก (`Mr.Buk` — เตรียมเปิดใช้งานกลางเดือนพฤศจิกายน 2026)

### ✅ ก. สิ่งที่ทำเสร็จสมบูรณ์แล้วสำหรับ มิสเตอร์บุก (Completed)
1. **ตั้งค่าระบบสะสมแต้มและคูปองใน LINE Official Account (`@misterbuk` / `@305lhvvt`) เปิดใช้งานจริงแล้ว:**
   - **บัตรสะสมแต้ม (`บัตรสะสมแต้ม มิสเตอร์บุก VIP`):** ลิงก์ `https://u.lin.ee/P44JSey` (สะสม 10 แต้ม / อายุบัตร 24 เดือน)
   - **กติกาการรับแต้มและของรางวัล 2 ระดับ (อัปเดตล่าสุด):**
     - **คิดจากยอดค่าสินค้าสุทธิ (ไม่รวมค่าจัดส่งและค่าปลายทาง) ทุก 500 บาท = รับ 1 แต้ม** (`490 บาท ไม่อนุโลม` ต้องซื้อให้ครบ 500 บาทขึ้นไปเท่านั้น)
     - **เก็บเศษยอดเงินสะสมทบไปออเดอร์ถัดไปอัตโนมัติ (`carryover_thb`):** เช่น สั่งเซ็ตคู่ `950.-` รับทันที `1 แต้ม` (ส่งรูป QR `1pt` ให้ติ๊กในบัตร LINE) + บอทเก็บเศษ `450 บาท` ผูกกับเบอร์โทรไว้ทบกับบิลถัดไป หรือหากบิลแรกสั่งถุง 1 กก. `490.-` (ยังไม่ครบ 500.-) บอทจะบันทึกยอดสะสม `490 บาท` (ขาดอีก 10 บาท) ไว้ทบกับบิลถัดไปให้อัตโนมัติค่ะ
     - **สะสมครบ 5 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิซองเล็ก `60 กรัม` จำนวน `3 ซอง` (มูลค่า 132.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
     - **สะสมครบ 10 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิถุงกลาง `500 กรัม` จำนวน `1 ถุง` (มูลค่า 249.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
   - **คูปองต้อนรับเพื่อนใหม่ VIP ลด 5% (`MRBUKVIP5`):** ลดทันที 5% ทุกโปรโมชั่นสำหรับการสั่งซื้อรอบถัดไป (1 กก. `490.-` เหลือ `465.-`, เซ็ตคู่ 41 มื้อ `950.-` เหลือ `902.-`, เซ็ต 30 ซอง `1,190.-` เหลือ `1,130.-`, เซ็ตใหญ่ 5 กก. `2,390.-` เหลือ `2,270.-`)
   - **Rich Menu (6 ปุ่ม) & ข้อความตอบกลับอัตโนมัติ (Auto-Response):** ตั้งค่าดักจับคีย์เวิร์ด `รับแต้ม`, `สะสมแต้ม`, `บัตรสะสมแต้ม`, `แลกแต้ม`, `รับสิทธิ์ลด 5%`, `ส่วนลด 5%`, `คูปองส่วนลด`, `MRBUKVIP5` ใน LINE OA Manager เรียบร้อยแล้วค่ะ
   - **ภาพ QR Code แจกแต้มแบบไม่มีวันหมดอายุ (Non-Expiring Point QR Codes):** บันทึกไว้ที่ `D:\MrBuk Content\Mr buk line oa\` ครบ 3 ระดับ (`MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png`) พร้อมระบบกันสแกนซ้ำของ LINE OA (สแกนรับแต้มได้สูงสุดวันละ 1 ครั้งต่อ 1 บัญชี)
   - **ไฟล์ใบแนบกล่องพัสดุ A5 สำหรับส่งโรงพิมพ์ (`D:\MrBuk print A5\300ppi\MrBuk print A5.jpg`):** ทำเสร็จเรียบร้อยแล้วค่ะ
2. **อัปเดตไฟล์ความรู้และกฎเหล็กเฉพาะของ มิสเตอร์บุก ([`messenger-engine/config_mrbuk.json`](file:///D:/chat%20bot/messenger-engine/config_mrbuk.json)) ครบ 100% แล้ว:**
   - แก้ไขข้อมูลใน `config_mrbuk.json` ให้เป็นข้อมูลจริงของ **มิสเตอร์บุก (`Mr.Buk`)** ทั้งหมด (ไม่ปะปนกับข้าวบุกสุขใจ): สัดส่วนแป้งบุก 46% (ผงบุก 54%) + ข้าวหอมมะลิแท้ 44% + น้ำ 10%, พลังงาน 23 kcal / คาร์บ 5g, เลข อย. `13-4-06169-6-0001` + ฮาลาล, เลขบัญชีธนาคารกสิกรไทย `989-2-13624-3` (บจก. ทูเคพี อิควิปเม้นท์), ราคาจริงครบทั้ง 4 โปรโมชั่นหลัก (`44.-`, `249.-`, `490.-`, `599.-`, `1,190.-`, `950.-`, `2,390.-`), และเพิ่มบล็อก `loyalty_program` + FAQ กติกาการแอด LINE `@misterbuk` สะสมแต้มเมื่อซื้อครบ 500 บาทเรียบร้อยแล้วค่ะ
3. **พัฒนาระบบสะสมแต้ม LINE OA แบบ Hybrid + ป้องกันการเคลมบิลซ้ำ 100% (`app/loyalty.py` + `database.py` + `media_generator.py` + `jst_erp.py` + `audit.py` + `main.py`) เสร็จสมบูรณ์พร้อมใช้งานจริง:**
   - **สลับโหลด `config_mrbuk.json` อัตโนมัติตาม `brand_id == "mrbuk"`:** เพิ่ม `load_brand_config(brand_id)` ใน [`app/config_loader.py`](file:///D:/chat%20bot/messenger-engine/app/config_loader.py) และ `_get_brand_config_and_llm(brand_id)` ใน [`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py) ให้แบรนด์มิสเตอร์บุกใช้ข้อมูลสินค้า บัญชีกสิกรไทย `989-2-13624-3` และโปรโมชั่นของมิสเตอร์บุกแยกขาดจากข้าวบุกสุขใจ 100%
   - **ซิงก์รูป QR Code แจกแต้ม (`1pt`, `2pt`, `4pt`) เข้า `app/static/media/` อัตโนมัติ:** อัปเดต [`app/media_generator.py`](file:///D:/chat%20bot/messenger-engine/app/media_generator.py) ให้คัดลอกไฟล์ `MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png` จาก `D:\MrBuk Content\Mr buk line oa\` เข้า `app/static/media/` พร้อมฟังก์ชัน `get_mrbuk_qr_media_for_points(points)` แตกยอดแต้มเป็นชุดรูป QR (`4pt`, `2pt`, `1pt`) อัตโนมัติ
   - **ตารางฐานข้อมูลสะสมแต้ม Hybrid & กันเคลมบิลซ้ำ ([`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py)):**
     - `LoyaltyMember` (`loyalty_members`): ผูกเบอร์โทร 10 หลัก (`phone` PK) กับ `line_user_id`, `fb_psid`, `total_points`, `lifetime_points`, `lifetime_spend_thb`, `pending_reward`, `redeemed_history`
     - `LoyaltyClaimedOrder` (`loyalty_claimed_orders`): บันทึก `order_ref` (`JST:<order_id>` และ `CHAT:<psid>:<msg_id>` พร้อม `ALIAS:` ล็อกข้ามระบบ) ป้องกันการนำบิลเดิมหรือเบอร์เดิม/ชื่อเดิมมาเคลมแต้มซ้ำ 100%
   - **โมดูลคำนวณแต้ม ยืนยันตัวตน และแลกของแถม ([`app/loyalty.py`](file:///D:/chat%20bot/messenger-engine/app/loyalty.py)):**
     - ยืนยันตัวตนใน LINE OA `@misterbuk` ได้ทั้ง **เบอร์โทรศัพท์ 10 หลัก** หรือ **ชื่อผู้รับ (`ชื่อ-นามสกุล`)** โดยค้นหาเชื่อมทั้ง `chatbot.db` (Facebook Messenger) และ `jst_erp` (`check_duplicate_order` + `search_jst_orders_by_receiver_name`)
     - กติกาคำนวณแต้มและเก็บเศษทบยอด (`extract_net_product_amount_thb` & `calculate_points_and_carryover`): หักค่าจัดส่ง/ค่าปลายทาง (`30`, `40`, `70` บาท) ออกก่อนเสมอ คิดจากยอดค่าสินค้าสุทธิครบทุก 500 บาท = 1 แต้ม (`490 บาท ไม่อนุโลม` ต้องครบ 500 บาทขึ้นไปเท่านั้น) พร้อมเก็บเศษยอดเงินที่เกินหรือยังไม่ครบ 500 บาท (`carryover_thb`) ไว้ในฐานข้อมูลของบอทเพื่อทบกับออเดอร์ถัดไปอัตโนมัติ (เช่น สั่ง `950.-` รับ `1 แต้ม` + เก็บเศษ `450.-` หรือสั่ง `490.-` บิลแรกรับ `0 แต้ม` + เก็บยอดสะสม `490.-` ขาดอีก 10 บาทครบ 500 บาทในบิลถัดไป)
     - กติกาแลกของแถม (`redeem_loyalty_points`): ครบ **5 แต้ม** แลกฟรีซองเล็ก `60g × 3 ซอง` (มูลค่า 132.-) / ครบ **10 แต้ม** แลกฟรีถุงกลาง `500g × 1 ถุง` (มูลค่า 249.-) รับพร้อมออเดอร์ถัดไป พร้อมบันทึก `[LOYALTY REWARD: ...]` ลงใน `pending_reward` และ `notes` ของลูกค้าอัตโนมัติ
   - **ฝั่ง Facebook Messenger ชวนแอด LINE สะสมแต้มอัตโนมัติ ([`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py)):** เมื่อลูกค้าสั่งซื้อในเพจมิสเตอร์บุก (`brand_id == "mrbuk"`) จนขึ้นสถานะปิดการขาย (`completed`) และมียอดได้รับแต้มตั้งแต่ 1 แต้มขึ้นไป ระบบจะต่อท้ายข้อความชวนแอด LINE OA `@misterbuk` (`https://u.lin.ee/P44JSey`) พร้อมแจ้งจำนวนแต้มที่ได้รับให้อัตโนมัติ
   - **รหัสสินค้า (`MRBUK*` SKU) ในระบบคลัง [`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py):** ผูกยอดเงินโปรโมชั่นมิสเตอร์บุก (`44`, `249`, `465`, `490`, `599`, `902`, `950`, `1130`, `1190`, `2270`, `2390` ฯลฯ) เข้ากับรหัส `MRBUK60G1`, `MRBUK500G1`, `MRBUK1KG1`, `MRBUK60G15`, `MRBUK60G30`, `MRBUK1KG2_60G1`, `MRBUK1KG5` เรียบร้อยแล้วค่ะ
   - **REST API สำหรับตรวจสอบและจัดการแต้ม ([`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py)):** `/api/loyalty/members`, `/api/loyalty/lookup`, `/api/loyalty/claim`, `/api/loyalty/redeem`

### ⚠️ ข. สิ่งที่ยังรอใส่ค่าจริงก่อนเปิดเพจ/LINE มิสเตอร์บุก (Pending Credentials)
1. **❌ รอใส่ Token จริงของ มิสเตอร์บุก (`mrbuk` — Slot 2) ใน `pages.json` หรือ `.env`:**
   - `MRBUK_LINE_CHANNEL_SECRET`, `MRBUK_LINE_CHANNEL_ACCESS_TOKEN` (ของ LINE OA `@305lhvvt`), `MRBUK_FB_PAGE_ID`, `MRBUK_FB_PAGE_ACCESS_TOKEN` (ของเพจ Facebook มิสเตอร์บุก)
2. **❌ รอใส่รูปตารางโปรโมชั่น 4 เซ็ตของ มิสเตอร์บุก (เมื่อออกแบบเสร็จ) และรหัสร้านค้า `JST_SHOP_ID` ของมิสเตอร์บุกใน JST ERP (หากแยกร้านกับข้าวบุกสุขใจ)**

---

## 5. กฎเหล็กการแยกแบรนด์/บริษัทเด็ดขาด 100% และการตั้งชื่อ + รูปโปรไฟล์บอทส่งรีพอร์ต (`workbot` @934ndvfs)

### 🔒 5.1 กฎเหล็กการแยกแบรนด์และบริษัทเด็ดขาด 100% (Strict Brand & Company Isolation Rule)
- ระบบแชทบอทนี้และกลุ่ม LINE สรุปรายงานเป็นของโปรเจกต์ **มิสเตอร์บุก (`Mr.Buk`)** และ **ข้าวบุกสุขใจ (`Buk Sukjai`)** เท่านั้น
- ดังนั้น **ห้ามนำชื่อบริษัทอื่น แบรนด์อื่น หรือมาสคอตของโปรเจกต์อื่นที่ไม่เกี่ยวข้อง มาใช้ตั้งชื่อบอท รูปโปรไฟล์ โค้ด หรือข้อความแจ้งเตือนในระบบนี้และในกลุ่ม LINE เด็ดขาดค่ะ** ต้องแยกขาดออกจากกันอย่างสิ้นเชิง

### ✅ 5.2 สิ่งที่เตรียมเสร็จแล้ว (รายชื่อใหม่แทน `GENIUS POINT` และคำสั่งสร้างรูปโปรไฟล์ 1:1 ทั้ง 3 สไตล์)
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

### ⚠️ 5.3 สิ่งที่ยังค้างคา (รอทำต่อในกลุ่มสรุปยอด)
- **❌ ยังไม่ได้เปลี่ยนชื่อจริงและรูปโปรไฟล์จริงในเว็บ `manager.line.biz` และในไฟล์ `pages.json`:**
  - ปัจจุบันบอทส่งรีพอร์ต (`@934ndvfs` Slot 5 `workbot`) ยังแสดงชื่อว่า **`GENIUS POINT`** (และบอทโค้ช `@346zyzej` Slot 6 `coachbot` ยังใช้ชื่อ **`Muzart พามู`**) ต้องนำรูปโปรไฟล์ 1:1 ไปอัปโหลดและกดเปลี่ยนชื่อ Account ใน `manager.line.biz` เป็น `Daily Report Bot` หรือ `Buk Report Bot` พร้อมอัปเดตฟิลด์ `"name"` ใน `messenger-engine/pages.json` และ `pages.default.json` ค่ะ


---

## 4. การแยกงานที่ยังไม่เสร็จออกเป็น 3 ส่วนชัดเจน (สำหรับแบ่งไปสั่งงานคนละแชท/คนละกลุ่ม)

### 🟢 ส่วนที่ 1: งานของ "กลุ่มคอมเมนต์ (Comment) & พัฒนาการตอบแชทหน้าร้าน"
* **ขอบเขต:** ดูแลเฉพาะคุณภาพคำตอบของน้องบุก (`@602xbpha` / เพจ FB) และการรับรูปแคปหน้าจอ + คอมเมนต์สอน AI จากคุณแอมมี่/คุณนัดในกลุ่ม `Comment (4)` (`@346zyzej` Muzart พามู)
* **ไฟล์ที่เกี่ยวข้อง:** `app/prompt_engine.py`, `app/audit.py`, `app/llm.py`, `config.json`, `audit_lessons_learned.json`
* **งานที่ยังค้างและต้องทำต่อในกลุ่มนี้:**
  1. เก็บตกและปรับปรุงสคริปต์การคุยตามคอมเมนต์ใหม่ๆ ในกลุ่ม `Comment (4)` อย่างต่อเนื่อง (รวมถึงตรวจเช็กให้กฎใหม่ล่าสุด เช่น ทวนออเดอร์แล้วไม่ต้องให้ลูกค้าพิมพ์ `"ยืนยัน"` ซ้ำ และห้ามพิมพ์ `"ดีมากๆค่ะ"` ตกคำว่า `"ยิน"` ทำงานแม่นยำ 100% ทุกเคส)
  2. อัปเดตข้อความต้อนรับของบอท `@346zyzej` บนเซิร์ฟเวอร์ให้เป็นข้อความเฉพาะของบอท AI Coach เต็มตัว

### 🔵 ส่วนที่ 2: งานของ "กลุ่มสรุปยอด (Summary, คลังสินค้า JST ERP, ขนส่ง & แจ้งเตือนเคส `#Q`)"
* **ขอบเขต:** ดูแลเฉพาะกลุ่มสรุปยอด (`@934ndvfs` GENIUS POINT ในกลุ่ม `C5e760c74d6b020ae8b8cc831970517dc` และ `C814be1f1cc536059190b79ac21d4e562`), รายงานยอดขาย-ตัดสต็อก 07:00 น., การคีย์ออเดอร์เข้าคลัง JST ERP, การแจ้งเลขพัสดุ และการกด Reply ตอบเคส `[#Q...]`
* **ไฟล์ที่เกี่ยวข้อง:** `app/daily_sheet_report.py`, `app/jst_erp.py`, `app/parcel_tracker.py`, `daily_report_state.json`, `parcel_tracking_state.json`
* **งานที่ยังค้างและต้องทำต่อในกลุ่มนี้:**
  1. ตรวจสอบความแม่นยำของยอดสรุป 07:00 น. ทุกเช้า และการคีย์ออเดอร์อัตโนมัติเข้าคลัง JST ERP ไม่ให้เกิดออเดอร์ซ้ำหรือตกหล่น
  2. ดูแลและต่ออายุ `JST_ERP_COOKIE` เมื่อคุกกี้ล็อกอินระบบคลังสินค้าหมดอายุตามรอบ
  3. ตรวจสอบการทำงานของระบบแจ้งเลขพัสดุอัตโนมัติ 2 ระยะ (ตอนจัดส่งออก + ตอนพัสดุถึงมือลูกค้า) และการกด Reply ตอบเคส `[#Q...]` จากในกลุ่มสรุปยอด

### 🟣 ส่วนที่ 3: งานส่วนอื่นๆ ที่แยกออกมา (ไม่เกี่ยวกับกลุ่มคอมเมนต์ และไม่เกี่ยวกับกลุ่มสรุปยอด)
* **ขอบเขต:** งานโครงสร้างเซิร์ฟเวอร์ Cloud (Render), ระบบจัดการโฟลว์ n8n, และการขยายบอทไปยังแบรนด์อื่นในฝั่งบริษัท ดิจิสท์ ฮับ / เอเจนซี่ Tori Marketing
* **ไฟล์ที่เกี่ยวข้อง:** `messenger-engine/n8n_workflows/*.json`, `render.yaml`, `pages.json`, `app/database.py`, `db_persistent_snapshot.json`, `.env`
* **สิ่งที่ทำเสร็จสมบูรณ์แล้วเมื่อวันที่ 4–6 พ.ย. 2026 (Completed 100%):**
  1. **✅ ผูกบัญชี GitHub `torithaimkt-tech` แยกบริษัทถาวร & ส่งโค้ดทั้ง 77 Commits (`0a20b98`) ขึ้น Render สำเร็จแล้ว:**
     - ตั้งค่า `git config --global credential.https://github.com.useHttpPath true` และล็อกอินบัญชี `torithaimkt-tech` ใน Git Credential Manager เรียบร้อยแล้ว
     - ส่งโค้ดชุดล่าสุดขึ้น `https://github.com/torithaimkt-tech/buksukjai-omnichannel.git` และอัปเดตเซิร์ฟเวอร์จริง `https://buksukjai-omnichannel.onrender.com` สำเร็จ 100%
  2. **✅ ระบบสำรองความจำแชทถาวรครบทุกช่องทาง 0 บาท (`/api/db/status`):**
     - อัปเกรด `save_persistent_snapshot()` และ `restore_persistent_snapshot_if_needed()` ใน [`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py) ให้จำครบทั้ง Facebook + LINE OA + LINE Group (รวม 183 ห้องแชท, 2,451 ข้อความ, และแต้มสะสม Loyalty) กู้คืนอัตโนมัติทันทีที่เซิร์ฟเวอร์ Render รีสตาร์ท
  3. **✅ ระบบต่ออายุคุกกี้ JST ERP อัตโนมัติ (`/api/jst/config`) & รายงานตรวจสุขภาพระบบทุกเช้า 07:00 น.:**
     - เพิ่ม Sliding Cookie Renewal ใน [`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py) และเพิ่มบล็อก **`🩺 เช็กสุขภาพระบบเช้านี้ (System Health Check)`** ต่อท้ายรายงานสรุปยอด 07:00 น. ใน [`app/daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py)
  4. **✅ กำแพงกั้นข้อมูลข้ามแบรนด์ 100% (`_resolve_brand_config_path()` & ด่าน `3.0 Hard Cross-Brand Isolation Wall`):**
     - ล็อกให้แต่ละแบรนด์อ่านเฉพาะไฟล์ตั้งค่าของตัวเองใน [`app/prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py) และ [`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py) ห้ามดึงโปรโมชันหรือเลขบัญชีของข้าวบุกสุขใจไปใช้เมื่อเปิดแบรนด์ใหม่เด็ดขาด
  5. **✅ ย้ายไฟล์ประวัติแชทดิบ 3 เพจมาเก็บในโฟลเดอร์ของฝั่งดิจิสท์ ฮับเรียบร้อยแล้ว:**
     - เก็บไว้ที่ `D:\buksukjai\chatbot-data\commentandmessage_3pages_raw` และ `D:\buksukjai\chatbot-data\customer_database_output_3pages`

---

## 6. เช็กลิสต์งานที่ยังค้างคาต้องทำต่อเนื่อง (Master Pending Checklist) & แม่แบบเปิดแบรนด์ใหม่ 6 ข้อ

### 📋 เช็กลิสต์งานที่ต้องทำต่อเนื่อง (เรียงตามลำดับความสำคัญ)
- [ ] **1. เปิดใช้งานบอทแบรนด์ที่ 2 — มิสเตอร์บุก (`mrbuk`):**
  - นำ `MRBUK_LINE_CHANNEL_SECRET`, `MRBUK_LINE_CHANNEL_ACCESS_TOKEN` (`@305lhvvt`), `MRBUK_FB_PAGE_ID`, และ `MRBUK_FB_PAGE_ACCESS_TOKEN` มาใส่ใน `pages.json` / `.env` และเปลี่ยน `"active": true`
  - อัปโหลดรูปตารางโปรโมชันจริงทั้ง 4 เซ็ตของมิสเตอร์บุกเข้าคลังรูปภาพบอท
- [ ] **2. เชื่อมบอทแบรนด์ลูกค้าของ Tori Marketing คิวถัดไป:**
  - **`LULUNA Almond Slice (luluna)`:** สร้าง `config_luluna.json` จากข้อมูลใน Skill `luluna-brand-specialist` และผูก Page Token / LINE Token
  - **`PADA Group (pada)`:** ตรวจทาน `config_pada.json` (ครอบคลุม `PADA Academy`, `PADA GOLF`, `GAVY Marketing`) และผูก Token จริง (`@506xhsrj`)
  - **`โซเพียว / โซมัส (sopure)` + `น้ำหนึ่ง หลานตาเพิ่ม`:** สร้าง `config_sopure.json` จากคลังความรู้ใน `D:\โซเพียว` เมื่อทีมงานพร้อมเปิดรับแชทอัตโนมัติ
- [ ] **3. เปลี่ยนชื่อและรูปโปรไฟล์บอทส่งรีพอร์ต (`@934ndvfs`) และบอทโค้ช (`@346zyzej`) ใน `manager.line.biz`:**
  - เปลี่ยนจากชื่อเดิม (`GENIUS POINT` / `Muzart พามู`) เป็นชื่อเฉพาะของระบบ เช่น `Daily Report Bot` / `AI Coach Bot` พร้อมอัปโหลดรูปโปรไฟล์ 1:1 ที่เตรียมคำสั่งไว้ในหมวดที่ 5.2
- [ ] **4. ตรวจสอบยอดสรุป 07:00 น. และสลับ `AUTO_SYNC_ENABLED = True` เต็มรูปแบบเมื่อแอดมินคนหยุดคีย์มือ:**
  - เช็กผลบล็อก `🩺 เช็กสุขภาพระบบเช้านี้` ในกลุ่ม LINE ทุกเช้า 07:00 น.
- [ ] **5. (ทางเลือกเสริมบนหน้าเว็บควบคุม) เพิ่มปุ่ม `"🔀 ดูผัง Flow แบบโหนด"` บนแถบด้านบนของ `index.html`:**
  - เพื่อให้กดดูผังเชื่อมโหนดและไฟล์เวิร์กโฟลว์ n8n ทั้ง 4 ตัวได้จากหน้าเว็บ `https://buksukjai-omnichannel.onrender.com/` โดยตรง

### 📝 แม่แบบ 6 ข้อสำหรับสั่งเปิดแบรนด์ใหม่ครั้งต่อไป (Brand Onboarding Template)
เมื่อคุณนัดต้องการเพิ่มแบรนด์ใหม่เข้าสู่ระบบ Flow ที่เสถียรแล้ว เพียงแจ้งข้อมูล 6 ข้อนี้ในแชทใหม่ได้เลยค่ะ:
1. **ชื่อแบรนด์และรหัสแบรนด์ (`brand_id`):** เช่น `luluna`, `sopure`, `mrbuk`
2. **รายการสินค้า ราคา โปรโมชัน และค่าจัดส่ง:** โอนส่งฟรีที่ยอดเท่าไหร่ / เก็บปลายทางบวกเพิ่มเท่าไหร่
3. **เลขบัญชีธนาคารรับโอนของแบรนด์นั้น:** ชื่อธนาคาร เลขบัญชี และชื่อบัญชี (ระบบจะล็อกด่านตรวจห้ามหลุดเลขบัญชีอื่น 100%)
4. **คำถามที่พบบ่อย (FAQ) 5–10 ข้อ:** เช่น วิธีทาน อายุการเก็บรักษา เลข อย. ลิงก์ Shopee/TikTok
5. **รูปตารางโปรโมชันของแบรนด์นั้น:** สำหรับให้บอทส่งรูปอัตโนมัติเมื่อลูกค้าถามราคา
6. **รหัสเพจและกุญแจเชื่อมต่อ (Page ID & Access Token):** ของ Facebook Page และ/หรือ LINE OA ของแบรนด์นั้นค่ะ
