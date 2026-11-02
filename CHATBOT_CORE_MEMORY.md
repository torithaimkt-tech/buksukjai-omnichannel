# 🧠 แกนกลางความจำระบบแชทบอท (Chatbot Core Memory & Master Status)
**อัปเดตล่าสุด:** 2 พฤศจิกายน 2026 (เวลา 10:20 น.)

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
7. **ระบบหยุดบอทชั่วคราวเมื่อเจอคำถามนอกสคริปต์ (Smart Escalation):**
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
1. **การเชื่อมบัญชี Render ใหม่ (`buksukjai@gmail.com`) เข้ากับ GitHub เพื่อ Deploy โค้ดแกนกลางชุดล่าสุดขึ้น Cloud 100%:**
   - บัญชี Render ใหม่ของ `buksukjai@gmail.com` (`Bukrice's workspace`) เปิดเสร็จแล้ว และโค้ดแกนกลางชุดล่าสุดอยู่ที่ GitHub `pordiporditeam-sudo/buksukjai-omnichannel`
   - **สิ่งที่ต้องทำต่อ:** กดเชื่อม GitHub `pordiporditeam-sudo/buksukjai-omnichannel` เข้ากับ Render ของ `buksukjai@gmail.com` (หรืออัปเดตโค้ดล่าสุดเข้า `torithaimkt-tech/buksukjai-omnichannel` ที่ผูกกับ `https://buksukjai-omnichannel.onrender.com` ปัจจุบัน)
2. **การผูกฐานข้อมูลถาวร (External PostgreSQL เช่น Supabase / Neon) แทน SQLite บน Render:**
   - เพื่อป้องกันไม่ให้ข้อมูลประวัติแชทฝั่ง LINE OA ถูกรีเซ็ตเมื่อมีการ Deploy เซิร์ฟเวอร์ใหม่
3. **การนำไฟล์ Workflow ทั้ง 4 ตัว ไปกด Import เข้าหน้ากระดาน `n8n` จริง (ภายใต้อีเมล `Tori Marketing`):**
   - เปิดหน้าเว็บ `n8n` Self-Hosted แล้วกด `Import from File` เลือกไฟล์ทั้ง 4 ตัวจาก [`D:\chat bot\messenger-engine\n8n_workflows\`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/)
4. **การผูก LINE OA และตั้งค่าบอทตัวที่ 4 (บอทแอดมินประสานงานฝั่ง `Tori Marketing`) และสล็อตแบรนด์อื่นๆ (`มิสเตอร์บุก`, `PADA AI`, `AIFY`, `Instagram DM`):**
   - ใส่ Channel Secret / Access Token ของ LINE OA ฝั่ง `Tori Marketing` ในโฟลว์ที่ 4 และใส่ Token ของเพจแบรนด์อื่นๆ ใน [`pages.json`](file:///D:/chat%20bot/messenger-engine/pages.json) เมื่อพร้อมเปิดใช้งานค่ะ


---

## 4. การเตรียมระบบแชทบอท & ระบบสะสมแต้ม LINE OA ของ มิสเตอร์บุก (`Mr.Buk` — เตรียมเปิดใช้งานกลางเดือนพฤศจิกายน 2026)

### ✅ ก. สิ่งที่ทำเสร็จสมบูรณ์แล้วสำหรับ มิสเตอร์บุก (Completed)
1. **ตั้งค่าระบบสะสมแต้มและคูปองใน LINE Official Account (`@misterbuk` / `@305lhvvt`) เปิดใช้งานจริงแล้ว:**
   - **บัตรสะสมแต้ม (`บัตรสะสมแต้ม มิสเตอร์บุก VIP`):** ลิงก์ `https://u.lin.ee/P44JSey` (สะสม 10 แต้ม / อายุบัตร 24 เดือน)
   - **กติกาการรับแต้มและของรางวัล 2 ระดับ (อัปเดตล่าสุด):**
     - **ทุกยอดสั่งซื้อ 500 บาท = รับ 1 แต้ม** (อนุโลมถุงใหญ่ 1 กก. `490.-` ร่วมรับ 1 แต้มได้ตามข้อความต้อนรับใน LINE OA)
     - **สะสมครบ 5 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิซองเล็ก `60 กรัม` จำนวน `3 ซอง` (มูลค่า 132.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
     - **สะสมครบ 10 แต้ม:** แลกรับฟรี! ข้าวบุกหอมมะลิถุงกลาง `500 กรัม` จำนวน `1 ถุง` (มูลค่า 249.-) — *รับของแถมฟรีไปพร้อมกับการสั่งซื้อครั้งถัดไป*
   - **คูปองต้อนรับเพื่อนใหม่ VIP ลด 5% (`MRBUKVIP5`):** ลดทันที 5% ทุกโปรโมชั่นสำหรับการสั่งซื้อรอบถัดไป (1 กก. `490.-` เหลือ `465.-`, เซ็ตคู่ 41 มื้อ `950.-` เหลือ `902.-`, เซ็ต 30 ซอง `1,190.-` เหลือ `1,130.-`, เซ็ตใหญ่ 5 กก. `2,390.-` เหลือ `2,270.-`)
   - **Rich Menu (6 ปุ่ม) & ข้อความตอบกลับอัตโนมัติ (Auto-Response):** ตั้งค่าดักจับคีย์เวิร์ด `รับแต้ม`, `สะสมแต้ม`, `บัตรสะสมแต้ม`, `แลกแต้ม`, `รับสิทธิ์ลด 5%`, `ส่วนลด 5%`, `คูปองส่วนลด`, `MRBUKVIP5` ใน LINE OA Manager เรียบร้อยแล้วค่ะ
   - **ภาพ QR Code แจกแต้มแบบไม่มีวันหมดอายุ (Non-Expiring Point QR Codes):** บันทึกไว้ที่ `D:\MrBuk Content\Mr buk line oa\` ครบ 3 ระดับ (`MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png`) พร้อมระบบกันสแกนซ้ำของ LINE OA (สแกนรับแต้มได้สูงสุดวันละ 1 ครั้งต่อ 1 บัญชี)
   - **ไฟล์ใบแนบกล่องพัสดุ A5 สำหรับส่งโรงพิมพ์ (`D:\MrBuk print A5\300ppi\MrBuk print A5.jpg`):** ทำเสร็จเรียบร้อยแล้วค่ะ
2. **อัปเดตไฟล์ความรู้และกฎเหล็กเฉพาะของ มิสเตอร์บุก ([`messenger-engine/config_mrbuk.json`](file:///D:/chat%20bot/messenger-engine/config_mrbuk.json)) ครบ 100% แล้ว:**
   - แก้ไขข้อมูลใน `config_mrbuk.json` ให้เป็นข้อมูลจริงของ **มิสเตอร์บุก (`Mr.Buk`)** ทั้งหมด (ไม่ปะปนกับข้าวบุกสุขใจ): สัดส่วนแป้งบุก 46% (ผงบุก 54%) + ข้าวหอมมะลิแท้ 44% + น้ำ 10%, พลังงาน 23 kcal / คาร์บ 5g, เลข อย. `13-4-06169-6-0001` + ฮาลาล, เลขบัญชีธนาคารกสิกรไทย `989-2-13624-3` (บจก. ทูเคพี อิควิปเม้นท์), ราคาจริงครบทั้ง 4 โปรโมชั่นหลัก (`44.-`, `249.-`, `490.-`, `599.-`, `1,190.-`, `950.-`, `2,390.-`), และเพิ่มบล็อก `loyalty_program` + FAQ กติกาการแอด LINE `@misterbuk` สะสมแต้มเมื่อซื้อครบ 500 บาทเรียบร้อยแล้วค่ะ
3. **โครงสร้างรองรับ `brand_id: "mrbuk"` ในโค้ดแกนกลาง (`messenger-engine`):**
   - จอง Slot 2 (`mrbuk` — `@305lhvvt`) ใน `pages.default.json` และ `pages.json`, มี Endpoint `/webhook/line/mrbuk` ใน `app/main.py`, ล็อกเลขบัญชีกสิกรไทย `989-2-13624-3` ใน `app/llm.py`, ล็อกเลข อย. `13-4-06169-6-0001` ใน `app/audit.py`, และมีฟังก์ชันค้นหาออเดอร์ย้อนหลังด้วยเบอร์โทร 10 หลัก (`normalize_thai_phone`) ใน `app/jst_erp.py` และ `app/parcel_tracker.py` พร้อมต่อยอดทันทีค่ะ

### ⚠️ ข. สิ่งที่ยังติด / ยังค้างคา / ยังทำไม่สำเร็จ สำหรับ มิสเตอร์บุก (Pending / Unfinished — รอทำช่วงกลางเดือน พ.ย. 2026)
1. **❌ ยังไม่ได้ใส่ Token ของ มิสเตอร์บุก (`mrbuk` — Slot 2) ใน `pages.json` / `.env`:**
   - `line_channel_secret`, `line_channel_access_token` (ของ LINE OA `@305lhvvt`), `fb_page_id`, `fb_page_access_token` (ของเพจ Facebook มิสเตอร์บุก) ยังเป็นค่าว่าง `""`
2. **❌ ยังไม่ได้เขียนโค้ดให้ `app/main.py` สลับโหลดไฟล์ `config_mrbuk.json` อัตโนมัติตาม `brand_id`:**
   - ปัจจุบัน `app/main.py` โหลด `CONFIG = load_config()` (`config.json` ของข้าวบุกสุขใจ) ตัวเดียวตอนเปิดเครื่อง ต้องปรับให้ `process_omnichannel_message` โหลด `config_mrbuk.json` เมื่อ `brand_id == "mrbuk"`
3. **❌ ยังไม่ได้ใส่รูปตารางโปรโมชั่นของ มิสเตอร์บุก และรูป QR Code แต้มสะสม (`1pt / 2pt / 4pt`) ลงใน `app/static/media/` และ `app/media_generator.py`:**
   - ต้องนำรูปโปรโมชั่นทั้ง 4 เซ็ตของมิสเตอร์บุก และไฟล์ `MrBuk_QR_Give_1pt.png`, `2pt`, `4pt` จาก `D:\MrBuk Content\Mr buk line oa\` มาใส่และแยกส่งตาม `brand_id == "mrbuk"`
4. **❌ ยังไม่ได้เขียนโมดูลเชื่อมยอดสั่งซื้อ Facebook / JST ERP เข้ากับระบบสะสมแต้ม LINE OA (`app/loyalty.py` หรือใน `database.py` + `main.py`):**
   - **ฝั่ง Facebook Messenger (เมื่อลูกค้าสั่งซื้อครบ 500 บาทขึ้นไป):** ต้องเพิ่มโค้ดให้บอทส่งข้อความชวนแอด LINE `@misterbuk` (พร้อมลิงก์ `https://u.lin.ee/P44JSey`) ท้ายการปิดการขาย (`#BUY<ยอดเงิน>`) อัตโนมัติ
   - **ฝั่ง LINE OA `@misterbuk` (เมื่อลูกค้าแอดไลน์มาแล้วยืนยันตัวตน):** ต้องเพิ่มโค้ดรับ **เบอร์โทรศัพท์ 10 หลัก** (หรือชื่อผู้รับ) จากลูกค้าในแชท LINE แล้วนำไปค้นหายอดสั่งซื้อจริงจาก `chatbot.db` และ `jst_erp.check_duplicate_order(phone)` พร้อมระบบป้องกันการเคลมบิลซ้ำ และส่งภาพ `MrBuk_QR_Give_1pt.png` / `2pt` / `4pt` อัตโนมัติ
5. **❌ ยังไม่ได้ตั้งค่ารหัสร้านค้า (`JST_SHOP_ID`) และรหัสสินค้า (`SKU`) ของ มิสเตอร์บุก ใน `app/jst_erp.py`**
6. **❓ โจทย์กติกาธุรกิจ 3 ข้อที่รอคุณนัดฟันธงก่อนเริ่มเขียนโค้ดช่วงกลางเดือน พ.ย. 2026:**
   - **ข้อที่ 1 (การคิดแต้มต่อบิล vs สะสมยอดทบข้ามบิล):** กรณีลูกค้าสั่งเซ็ตคู่ `950 บาท` จะให้คิดแบบ **"ตัดตามบิล = รับ 1 แต้ม (หรือปัดขึ้นให้ 2 แต้ม)"** หรือให้ **"รับ 1 แต้ม แล้วเก็บเศษ 450 บาทไว้ทบกับบิลถัดไป"** ในฐานข้อมูลคะ?
   - **ข้อที่ 2 (สิทธิ์ของถุงใหญ่ 1 กก. ราคา `490 บาท`):** ยืนยันตามข้อความต้อนรับใน LINE OA ปัจจุบันเลยไหมคะว่า ถ้าลูกค้าซื้อถุงใหญ่ 1 กก. (`490.-` ซึ่งขาดอีก 10 บาทจะครบ 500) **อนุโลมให้ได้รับ 1 แต้มเต็มทันที**?
   - **ข้อที่ 3 (รูปแบบการเก็บแต้ม):** แนะนำให้ทำแบบ **Hybrid (คู่ขนาน)** คือบันทึกแต้มผูกกับเบอร์โทรไว้ในฐานข้อมูล `chatbot.db` ของบอทด้วย **พร้อมกับ** ส่งรูป QR Code ให้ลูกค้ากดสะสมในบัตร LINE Reward Card ด้วย เผื่อลูกค้าผู้สูงอายุสแกน QR ไม่เป็น บอทและแอดมินก็ยังเช็กแต้มจากเบอร์โทรให้ลูกค้าได้ 100% ค่ะ

---

## 5. กฎเหล็กการแยกแบรนด์/บริษัทเด็ดขาด 100% และการตั้งชื่อ + รูปโปรไฟล์บอทส่งรีพอร์ต (`workbot` @934ndvfs)

### 🔒 5.1 กฎเหล็กห้ามปะปนกับบริษัทใหม่เด็ดขาด 100% (Strict Shareholder & Company Isolation Rule)
- ระบบแชทบอทนี้และกลุ่ม LINE สรุปรายงานเป็นของโปรเจกต์ **มิสเตอร์บุก (`Mr.Buk`)** และ **ข้าวบุกสุขใจ (`Buk Sukjai`)** ซึ่งคุณนัดมีหุ้นส่วนฝั่งเดิมที่ **ไม่รู้เรื่องบริษัท พอดิพอดี เฮาส์ จำกัด (`Pordipordi House`) และแบรนด์พอดีสุข (`Pordisuk`) เลยแม้แต่นิดเดียว และห้ามรู้เด็ดขาด 100%**
- ดังนั้น **ห้ามนำชื่อ `Pordipordi` / `พอดิพอดี` / `พอดีสุข` / ชื่อมาสคอต (`ทูลี่` / `ขุนสุข`) หรือสิ่งใดที่เชื่อมโยงกับบริษัทใหม่มาใช้ตั้งชื่อบอท รูปโปรไฟล์ หรือข้อความแจ้งเตือนในระบบนี้และในกลุ่ม LINE เด็ดขาดค่ะ** ต้องแยกขาดออกจากกันอย่างสิ้นเชิง

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
