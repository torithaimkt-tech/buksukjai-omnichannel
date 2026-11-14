# 🧠 แกนกลางความจำระบบแชทบอท (Chatbot Core Memory & Master Status)
**อัปเดตล่าสุด:** 11 พฤศจิกายน 2026 (Commit `46fc7a6` — เปิดบอท `BUK TEAM @934ndvfs` ล็อกเฉพาะ **`กลุ่มบูม`** กลุ่มเดียว เพื่อรายงานเฉพาะสต็อกคงเหลือ **ข้าวบุกสุขใจ** ทุกเช้า 07:00 น.)

เอกสารนี้คือ **แกนกลางความจำหลัก (Single Source of Truth)** ของระบบแชทบอททั้งหมดในโปรเจกต์ `D:\chat bot` (และ [`messenger-engine/CORE_SYSTEM_MEMORY.md`](file:///D:/chat%20bot/messenger-engine/CORE_SYSTEM_MEMORY.md)) เพื่อให้สามารถเปิดแชทใหม่และทำงานต่อได้ทันทีโดยไม่สูญเสียข้อมูลแม้จะลบแชทเดิมทิ้งค่ะ

---

## 1. สถาปัตยกรรมแชทบอททั้ง 4 ตัว (4-Bot Isolated Architecture)

> **กฎเหล็กการออกแบบ:**
> - **1 กลุ่ม LINE = มีบอททำงานแค่ 1 ตัวเท่านั้น** เพื่อป้องกันบอทตีกันหรือส่งรายงานผิดกลุ่ม
> - **แยกอีเมล Render แบรนด์ละ 1 อีเมล** (`buksukjai@gmail.com` แยกจาก `Tori Marketing`) เพื่อใช้โควตาฟรี `Free 750 hrs/mo` แยกกัน ไม่เสียเงิน \$7/เดือน
> - **n8n ใช้แบบ Self-Hosted ฟรีไม่จำกัดโฟลว์** ภายใต้อีเมลของ `Tori Marketing` โดยแยกเป็น 4 โฟลว์อิสระสำหรับบอทแต่ละตัว (ไฟล์แม่แบบอยู่ใน [`messenger-engine/n8n_workflows/`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/))

| ลำดับ | ชื่อบอท | บทบาทหน้าที่ | LINE ID / ช่องทาง | `brand_id` ในระบบ | กลุ่ม LINE ที่ประจำการ | Webhook URL |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ตัวที่ 1** | **น้องบุก (Sales Bot)** | ตอบแชทขายของหน้าร้าน ดูแลลูกค้า ปิดการขาย ทวนออเดอร์ ส่ง `#BUY` ขุดแชท และแจ้งเลขพัสดุ | `@602xbpha` + เพจ FB ข้าวบุก สุขใจ (`806129109240845`, LINE Channel ID: `2009665645`) | `buksukjai` | แชทส่วนตัวลูกค้า 1-on-1 (LINE OA & FB Messenger) | `https://buksukjai-omnichannel-twht.onrender.com/webhook/line/buksukjai` และ `/webhook/facebook` |
| **ตัวที่ 2** | **BUK TEAM (Stock Bot กลุ่มบูม)** | รายงาน **เฉพาะสต็อกคงเหลือ ข้าวบุกสุขใจ แบรนด์เดียว** ทุกเช้า 07:00 น. (ห้ามส่งยอดขาย/ข้อมูลลูกค้า และห้ามตอบกลุ่มอื่นเด็ดขาด) | `BUK TEAM` (`@934ndvfs`, Channel ID: `2009741913`) | `workbot` | เฉพาะ **`กลุ่มบูม`** เท่านั้น (บล็อกกลุ่มสรุปยอดเดิม 100%) | `https://buksukjai-omnichannel-twht.onrender.com/webhook/line/workbot` |
| **ตัวที่ 3** | **บอทรับคอมเมนต์สอน AI (AI Coach Bot)** | รับรูปแคปหน้าจอ + คอมเมนต์จากคุณแอมมี่และคุณนัดในกลุ่ม `Comment` เพื่ออัปเดตกฎการตอบของน้องบุกแบบถาวร (ห้ามส่งข้อความหาลูกค้าเด็ดขาด) | `Muzart พามู` (`@346zyzej`, Provider: `BukSukjai`, Channel ID: `2012318669`) | `coachbot` | กลุ่ม **`Comment (4)`** (`Cf0c8835b5b0711e80f7350ffc9af66f1`) | `https://buksukjai-omnichannel-twht.onrender.com/webhook/line/coachbot` |
| **ตัวที่ 4** | **บอทแอดมินประสานงาน Tori Marketing** | บอทประสานงานและรับแจ้งเตือนฝั่งเอเจนซี่ Tori Marketing (แยกไปใช้ Render ของ `torithaimkt@gmail.com`) | `AIFY` (`@599fgktd`, Channel ID: `2012318539`, Secret: `2e841449fe0466ebba1abcf68953966b`) | `torimarketing_admin` / `aify` | กลุ่มประสานงาน Tori Marketing | แยกโฮสต์ฝั่ง `Tori's workspace` (`torithaimkt@gmail.com`) และโฟลว์ [`4_torimarketing_admin_bot.json`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/4_torimarketing_admin_bot.json) |

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
9. **ระบบหยุดบอทชั่วคราวเมื่อเจอคำถามนอกสคริปต์ (Smart Escalation) & กฎเหล็กห้ามส่ง `[#Q...]` พร่ำเพรื่อ (อัปเดต 6–8 พ.ย. 2026):**
   - หากลูกค้าถามคำถามแปลกใหม่ที่ AI ไม่มั่นใจจริงๆ บอทจะตอบรับลูกค้าอย่างสุภาพ พักบอทเฉพาะแชทนั้น (`pause_session_for_admin_review`) และส่งแจ้งเตือน `[#Q...]` เข้ากลุ่มสรุปยอด
   - **กฎเหล็กห้ามแจ้งเตือน `[#Q...]` เด็ดขาดใน 2 กรณีนี้:**
     1. **ลูกค้าถามราคา/โปรโมชั่นทั่วไป** (เช่น เคสคุณ `อาภรณ์ ก้านกนก` พิมพ์ `"สนใจ ขอรายละเอียดโปรโมชั่นค่ะ"` ห้ามตีความเป็นคำถามเรื่องโรคประจำตัวเด็ดขาด ต้องส่งตารางโปรโมชั่นทันที)
     2. **ลูกค้าส่งสลิปโอนเงินพร้อมชื่อ-ที่อยู่** (เช่น เคสคุณ `Dusanee Mak` `"ดุษณี มักเจริญลาภ จ.สมุทรปราการ"` ห้ามหยุดบอทแล้วส่ง `[#Q...]` ว่าไม่แน่ใจสลิป ให้บอทกล่าวขอบคุณ ทวนรายการสั่งซื้อ ส่ง `#BUY<ยอดเงิน>` และให้ระบบหลังบ้านตรวจ QR สลิป + แนบสลิปเข้าคลัง JST ERP อัตโนมัติ)
10. **กฎมาตรฐานส่วนผสม โภชนาการ & การจัดส่งของ ข้าวบุกสุขใจ (อัปเดต 14 พ.ย. 2026):**
   - **ส่วนผสม/โภชนาการตามฉลาก:** บุก 59% ผสมข้าวหอมมะลิแท้ 29% และน้ำ 12% พลังงาน **23 kcal ต่อข้าวสุก 25 กรัม** (คาร์บ 5.2g น้ำตาล 0g ไขมัน 0g โซเดียม 0mg) — **ห้ามพูดว่า *"ลดแป้งลงครึ่งหนึ่ง"* หรือ *"ต่ำกว่าเกือบครึ่ง"* เด็ดขาด และทุกครั้งที่แจ้งตัวเลข `23 kcal` ต้องระบุหน่วย *"ต่อข้าวสุก 25 กรัม"* กำกับเสมอ** (และห้ามพูดว่า *"ผสมบุก 60% ข้าว 40%"* เด็ดขาด)
   - **การจัดส่ง & ขั้นต่ำ:** จัดส่งทั่วไทย **3–5 วัน**, **ไม่มีขั้นต่ำในการสั่งซื้อ**, ต่ำกว่า 1 กก. โอน +30฿ / ปลายทาง +70฿, สั่ง 1 กก. ขึ้นไป โอนส่งฟรี / ปลายทาง +40฿ค่ะ
11. **กฎเหล็กกลุ่มสรุปยอด: ห้ามเด้งสรุปยอดระหว่างวัน ให้เด้งวันละ 1 ครั้งตอน 07:00 น. เท่านั้น (อัปเดต 6 พ.ย. 2026):**
   - ล็อก [`daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py) ให้ส่งข้อความสรุปยอดเข้ากลุ่ม LINE สรุปยอดเฉพาะช่วงเวลา `07:00–07:59 น.` วันละ 1 ครั้งเท่านั้น (`last_line_summary_target_date`) ห้ามเด้งซ้ำทุกครั้งที่อัปเดตโค้ดหรือรีสตาร์ทเซิร์ฟเวอร์เด็ดขาดค่ะ
12. **สถาปัตยกรรมแหล่งข้อมูลเดียว (Single Source of Truth) & การลบลิงก์เก่า `asia-web.jsterp.com` ทิ้งถาวร 100% (อัปเดต 8 พ.ย. 2026 — Commit `7feae4f` & `f597570`):**
   - **ลบคุกกี้เก่าที่ฝังในโค้ด (`FRESH_JST_COOKIE` และ `_LATEST_JST_COOKIE`) ทิ้งถาวร:** ห้ามฝังคุกกี้คงที่ไว้ในไฟล์ `.py` อีกเด็ดขาด ให้ใช้คุกกี้จาก [`messenger-engine/jst_sync_state.json`](file:///D:/chat%20bot/messenger-engine/jst_sync_state.json) (`persisted_cookie`) เพียงจุดเดียว ซึ่งต่ออายุ Sliding `.AspNetCore.GlobalAuthCookie` อัตโนมัติทุกครั้งที่เรียกใช้งาน
   - **ลบลิงก์ `https://asia-web.jsterp.com` ที่ตายแล้วออกจากระบบ 100% (`0` จุดในระบบ):** ย้ายทุกฟังก์ชันใน [`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py) มาต่อตรงเข้า `https://asia.jsterp.com` เพียงเส้นทางเดียว:
     - **การสร้างออเดอร์ (`create_order_in_jst`):** ใช้ `https://asia.jsterp.com/Common/FileImport/FileImport` คู่กับไฟล์แม่แบบ `app/jst_order_template.xlsx` (`RelativeId="order"`, `ImportType="increase"`)
     - **กฎสำคัญของ `FileImport` สำหรับออเดอร์โอนเงินที่มีค่าส่ง (`+30฿`):** เมื่อ `"COD": "ไม่"` ระบบ `FileImport` ของ JST ERP จะปฏิเสธแถวที่ใส่ `"ค่าขนส่ง"` แยกหรือใส่สถานะ `"ชำระแล้วรอตรวจสอบ"` ดังนั้นโค้ดใน `create_order_in_jst` จึงล็อกให้ใส่ `"สถานะ": "รอชำระเงิน"`, `"ค่าขนส่ง": "0"`, และบวกค่าส่งเข้าใน `"ราคาสินค้าต่อหน่วย"` (เช่น `500g` โอน = `269`) จากนั้นจึงอัปโหลดสลิปผ่าน `/Intergration/Upload/UploadAttachement` + `/OMS/MiniShopOrder/UploadReceipt`, กดยืนยันสลิป `/OMS/MiniShopOrder/ConfirmOrder`, และกดส่งเข้าคลัง `/OMS/Order/Audit` เพื่อออกเลขพัสดุ J&T Express อัตโนมัติ
   - **รวมและล็อกฐานข้อมูล `chatbot.db` ให้มีจุดเดียวแบบ Absolute Path:** ล็อก `DEFAULT_SQLITE_URL` ใน [`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py) ให้ชี้เข้า `D:/chat bot/messenger-engine/chatbot.db` ตายตัว (รวมข้อมูล 250 เซสชันจากก้อนนอกเข้ามาครบถ้วน) และลบไฟล์ซ้ำ/ไฟล์ร้างทิ้งถาวรแล้ว 9 ไฟล์ (`d:\chat bot\chatbot.db`, `d:\chat bot\config.json`, `buksukjai_chat.db`, `conversations.db`, `server.js`, `system-prompt.js`, `package.json`, `package-lock.json`, `start-inbox.bat`) พร้อมล้างไฟล์สคริปต์ชั่วคราวใน `scratch/` ทิ้งทั้งหมด 127 ไฟล์ค่ะ
   - **บันทึกสถานะออเดอร์วันที่ 6–8 พ.ย. 2026 ครบ 100%:**
     - **ศุกร์ 6 พ.ย. 2026:** คีย์และออกเลขพัสดุ J&T Express ครบทั้ง 25 ออเดอร์ (เพจ FB 16 รายการ + TikTok 9 รายการ = `14,043.36฿`)
     - **เสาร์ 7 พ.ย. 2026:** คีย์ แนบสลิป ยืนยันการชำระเงิน และออกเลขพัสดุ J&T Express ครบทั้ง 18 ออเดอร์เพจ FB (`9,532.00฿`, เลขใบสั่งซื้อ `#243480` ถึง `#243515`) + 8 ออเดอร์ TikTok (`2,242.18฿`) รวม 26 ออเดอร์ = `11,774.18฿` พร้อมอัปเดต Google Sheets และส่งรายงานเข้ากลุ่มสรุปยอดเรียบร้อยแล้วค่ะ
     - **อาทิตย์ 8 พ.ย. 2026:** คีย์และออกเลขพัสดุให้ `คุณ Palm Anthika Milinsiranan` (`อัญญ์ฐิกา มิลินศิรนันท์`, `088-7945929`, `500g` โอน `269฿`) -> ใบสั่งซื้อ `#243621` | J&T Express `864938128305` (และ `คุณวีนัส โฆษิตสกุล` `#243050` | J&T Express `864927219125`) เรียบร้อยแล้วค่ะ
13. **ระบบกระชับความแข็งแกร่ง 5 ด้านแบบ 0 บาท (5-System Zero-Cost Hardening — Commit `39e07fd`):**
   - **ระบบที่ 1 — แยกประเภทรูปภาพด้วย AI Vision & ตรวจสลิปครบ 4 เงื่อนไข ([`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py), [`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py)):**
     - `classify_incoming_chat_image()` แยกประเภทรูปที่ลูกค้าส่งเข้ามาก่อนเสมอว่าเป็น `(1) รูปสลิปโอนเงิน ([IMAGE:...])`, `(2) รูปตารางโปรโมชั่น/สินค้า ([IMAGE_PROMO:...])`, หรือ `(3) รูปพัสดุ/ของเสียหาย ([IMAGE_PARCEL:...])` ป้องกันบอทเห็นรูปตารางโปรแล้วเข้าใจผิดว่าเป็นสลิป 100%
     - `verify_and_auto_confirm_jst_slips()` ตรวจสลิปโอนเงินจากแชทครบ 4 ข้อ: `(1) มีรหัสอ้างอิง QR/Ref`, `(2) ชื่อบัญชีผู้รับตรง (ดิจิสท์ ฮับ / ลงท้าย 7545-5 หรือ มิสเตอร์บุก 13624-3)`, `(3) ยอดเงินตรงกับออเดอร์`, และ `(4) เลข Ref ไม่เคยถูกใช้ซ้ำมาก่อน (claimed_slip_refs.json)` หากขาดข้อใดข้อหนึ่งจะไม่กดยืนยันเอง และส่งแจ้งเตือนเข้ากลุ่ม LINE ทันที
   - **ระบบที่ 2 — ตัวดักจับที่อยู่ไม่ครบ & เบอร์โทรไม่ครบ 10 หลัก ([`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py), [`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py)):**
     - `translate_thai_numerals()` แปลงเลขไทย (`๐-๙`) เป็นเลขอารบิก (`0-9`) อัตโนมัติ, แยกเบอร์โทรที่พิมพ์ติดกับรหัสไปรษณีย์ 5 หลัก (เช่น `201300812345678`), และกวาดรวมข้อความจาก 5 บับเบิลล่าสุดของลูกค้ามาต่อกันก่อนตรวจ
     - ใช้รหัสไปรษณีย์ขึ้นต้นด้วย `10xxx` หรือคำว่า `กทม./กรุงเทพ/แขวง/เขต` เพื่อรู้ทันทีว่าเป็นกรุงเทพฯ (ไม่ไปทวงถาม `ตำบล/อำเภอ` กับลูกค้า กทม.) และหากลูกค้าพิมพ์เบอร์โทรตกหล่น (`9 หลัก` หรือ `11 หลัก`) บอทจะทักทวนเบอร์โทรอย่างสุภาพก่อนปิดออเดอร์
   - **ระบบที่ 3 — ตัวรวมข้อความเมื่อลูกค้าพิมพ์ซอยถี่ๆ (Debounce) & ลูปดึงแชท Facebook ความเร็วสูง 20 วินาที ([`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py), [`app/followup.py`](file:///D:/chat%20bot/messenger-engine/app/followup.py)):**
     - `enqueue_debounced_omnichannel_message()` หน่วงเวลารอรวมข้อความที่ลูกค้าพิมพ์ซอยหลายบรรทัดติดกัน (`3.5 วินาที` สำหรับข้อความทั่วไป และ `6–8 วินาที` สำหรับคำตอบสั้นๆ `<= 12 ตัวอักษร`) โดยหยิบ `reply_token` ของข้อความสุดท้ายใน LINE OA มาใช้ตอบกลับ ทำให้ยังส่งข้อความฟรี 100%
     - แยกลูป `_fast_facebook_chat_responder_loop()` ออกมาดึงแชท Facebook ตอบกลับทุกๆ **20 วินาที** แยกขาดจากงานซิงก์คลังสินค้า JST ERP ที่รันทุก 10 นาที
   - **ระบบที่ 4 — แจ้งเตือนคุกกี้ JST / Token เพจหมดอายุเฉพาะตอนเช้า & คิวออเดอร์สำรอง (`pending_jst_retry_queue`):**
     - ตรวจสอบสุขภาพคุกกี้ JST ERP และ Facebook Page Token (`check_and_alert_fb_page_token_health`) โดยแจ้งเตือนเข้ากลุ่ม LINE **สูงสุดวันละ 1 ครั้งเฉพาะตอนเช้า** (ห้ามเด้งรบกวนตอนกลางคืน `22:00–06:59 น.` เด็ดขาด) พร้อมเก็บออเดอร์ที่คีย์ไม่ผ่านลงคิวสำรองเพื่อซิงก์ซ้ำอัตโนมัติทันทีที่ต่ออายุคุกกี้
   - **ระบบที่ 5 — ระบบจำที่อยู่ลูกค้าเก่า สั่งซ้ำคลิกเดียว (`One-Click Repeat Order`):**
     - `get_saved_customer_address_profile(psid)` ดึงชื่อ เบอร์โทร และที่อยู่จัดส่งเดิมของลูกค้าเก่าที่เคยสั่งสำเร็จขึ้นมาให้บอททวนถามในขั้นตอนเดียว (*"จัดส่งตามที่อยู่เดิมของ คุณ... เลยไหมคะ และรอบนี้รับเป็น โอนส่งฟรี หรือ เก็บปลายทาง ดีคะ"*)
14. **อนุมัติออเดอร์ Shopee / TikTok / บัตรเครดิต อัตโนมัติ & แจ้งต้นตอแชทในใบเตือนสลิป (`Commit f1c46d7` & `89c1102`):**
   - ออเดอร์ที่มาจาก **Shopee, TikTok, Lazada หรือชำระผ่านบัตรเครดิต (`บัตรเครดิต`)** ผ่านการตรวจสอบยอดเงินจากแพลตฟอร์มมาแล้ว ระบบ `verify_and_auto_confirm_jst_slips()` จะกดยืนยันเข้าคลัง JST ERP (`confirm_jst_order_payment`) ให้อัตโนมัติทันทีโดยไม่ต้องตรวจ QR สลิปโอนเงิน และไม่เด้งแจ้งเตือนว่าสลิปไม่ผ่าน
   - สำหรับออเดอร์โอนเงินผ่านแชทที่สลิปมีปัญหาจริง ระบบจะแสดง **`📍 ต้นตอแชท`** (`_resolve_slip_order_origin_trace`), เวลาสั่งซื้อ, และรายการสินค้า/ยอดเงิน เพื่อให้แอดมินตามหาแชทลูกค้าเจอได้ทันทีใน 1 วินาที
15. **ตัดหัวข้อภายในบริษัท & ตัดลิงก์ Google Sheets ออกจากท้ายรายงานสรุปยอด 07:00 น. (`Commit 3b0a115`):**
   - ในฟังก์ชัน `format_line_group_daily_summary()` ([`app/daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py#L1168-L1183)):
     1. ตัดบรรทัด `🟢 ด่านกั้นข้อมูลข้ามบริษัท/แบรนด์` ออกจากข้อความรีพอร์ต (ให้ทำงานเฉพาะหลังบ้านอย่างเดียว ไม่นำมาโชว์ในรายงาน)
     2. ตัดลิงก์ `📊 ดูตารางรายชื่อและรายละเอียดใน Google Sheets` ด้านล่างสุดออก เพื่อให้รายงาน 07:00 น. คลีน กระชับ และพร้อมใช้งานทันที
16. **ระบบอ่านบริบทคำตอบสั้นๆ (`Context-Aware Short Reply Resolver`) & รอจังหวะพิมพ์ต่อ (`Smart Context Wait`) (`Commit 6f5fd61`):**
   - เพิ่ม `get_last_assistant_context()`, `is_polite_decline_or_refusal_in_context()`, `is_short_conversational_acknowledgement()`, `is_genuine_question_text()`, และ `resolve_contextual_short_reply()` ใน [`app/llm.py`](file:///D:/chat%20bot/messenger-engine/app/llm.py#L448-L685) และ [`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py#L418-L480)
   - เมื่อลูกค้าตอบสั้นๆ เช่น **`"ไม่คะ"`, `"ไม่ค่ะ"`, `"ยังค่ะ"`, `"ไม่เอาค่ะ"`, `"ผ่านก่อน"`, `"ไม่มีค่ะ"`, `"ค่ะ"`, `"โอเคค่ะ"`, `"ขอบคุณค่ะ"`** ระบบจะดึงประโยคคำถามก่อนหน้าของบอท/แอดมิน (`prev_bot_msg`) มาเทียบเสมอ ตอบรับอย่างสุภาพเป็นธรรมชาติ และ **ห้ามตีความเป็นคำถามแปลกใหม่ (`[#Q1]`) เด็ดขาด**
   - ขยายเวลารอบริบท (`Smart Context Wait`) เป็น `6–8 วินาที` บน Webhook และ `45 วินาที` บนระบบดึงแชท Facebook เมื่อลูกค้าพิมพ์คำสั้นๆ หรือเมื่อแอดมินเพิ่งคุยกับลูกค้าอยู่
17. **กฎเหล็กเมื่อเจอคำถามแปลกใหม่: บอทต้องเงียบฝั่งลูกค้า 100% และส่งมาบอกในกลุ่มสรุปยอดอย่างเดียว (`Silent Customer Escalation Rule` — คุณแอมมี่ & คุณนัด, `Commit b97f503`):**
   - เมื่อมีคำถามแปลกใหม่นอกเหนือข้อมูลมาตรฐานจริงๆ ที่บอทไม่มั่นใจ (`escalate_to_line_group = True` ใน [`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py#L1050-L1085) และ [`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py#L1014-L1035)):
     1. **ฝั่งแชทลูกค้า:** บอทต้อง **เงียบไปเลย 100% (`bubbles = []`)** ห้ามส่งข้อความ *"ขอบพระคุณสำหรับคำถามนะคะ... ขออนุญาตส่งเรื่องให้พี่แอดมิน"* ไปหาลูกค้าเด็ดขาด และพักบอทเฉพาะแชทนั้นไว้รอแอดมิน
     2. **ฝั่งกลุ่ม LINE สรุปยอด:** ส่งแจ้งเตือน `[#Q...]` เข้ากลุ่มสรุปยอดให้พี่แอดมินทราบตามปกติ (แสดงสถานะ `🔇 สถานะบอท : เงียบไว้และพักบอทชั่วคราว (ไม่ได้ส่งข้อความขัดจังหวะลูกค้าค่ะ)`)

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

## 4. การเตรียมระบบแชทบอท, ระบบสะสมแต้มคู่ขนาน & แผนการตลาด LINE OA ของ มิสเตอร์บุก (`Mr.Buk` — อัปเดตข้อตกลงล่าสุดของคุณแอมมี่ & คุณนัด 8 พ.ย. 2026)

### ✅ ก. สิ่งที่ทำเสร็จสมบูรณ์แล้วสำหรับ มิสเตอร์บุก (Completed 100%)
1. **กติกาหลักของระบบคูปอง & บัตรสะสมแต้มใน LINE Official Account (`@misterbuk` / `@305lhvvt`) ตามข้อตกลงของคุณแอมมี่ & คุณนัด:**
   - **สงวนสิทธิ์สะสมแต้มและเก็บคูปองเฉพาะยอดที่สั่งซื้อผ่าน LINE OA (`@misterbuk`) เท่านั้น (LINE-Only Loyalty & Coupon):**
     - ดึงลูกค้าเข้า LINE OA ด้วย **คูปองส่วนลดต้อนรับเพื่อนใหม่ 5% (`MRBUKVIP5`)**
     - **ไม่ดึงยอดข้ามมาจากเพจ Facebook** จึง **ไม่ต้องให้ลูกค้าพิมพ์เบอร์โทรศัพท์ 10 หลักเพื่อเช็กแต้ม** เพราะลูกค้าสั่งซื้ออยู่ในห้องแชท LINE OA โดยตรง ระบบบอทจะผูกแต้มและจำเศษเงินสะสม (`carryover_thb`) เข้ากับ **บัญชี LINE (`line_user_id`) ของลูกค้าคนนั้นโดยตรงอัตโนมัติทันทีค่ะ!**
   - **บัตรสะสมแต้ม (`บัตรสะสมแต้ม มิสเตอร์บุก VIP`):** ลิงก์ `https://u.lin.ee/P44JSey` (สะสม 10 แต้ม / อายุบัตร 24 เดือน)
   - **กติกาการคำนวณแต้ม & ระบบเก็บเศษเงินทบยอดคู่ขนาน (`carryover_thb`):**
     - **หักค่าจัดส่งและค่าเก็บเงินปลายทาง (`30`, `40`, `70` บาท) ออกก่อนเสมอ (`extract_net_product_amount_thb`)** ไม่นำค่าส่งมาคิดแต้มเด็ดขาด
     - **ยอดค่าสินค้าสุทธิครบทุก 500 บาท = รับ 1 แต้ม (`490 บาท ไม่อนุโลม` ต้องซื้อให้ครบ 500 บาทขึ้นไปเท่านั้น)**
     - **เก็บเศษยอดเงินสะสมทบไปบิลถัดไปอัตโนมัติ (`carryover_thb`):**
       - สั่งเซ็ตคู่ขายดี `950.-` (หรือเก็บปลายทาง `990.-` หักค่าส่ง `40.-` เหลือค่าสินค้าสุทธิ `950.-`) $\rightarrow$ **รับทันที `1 แต้ม`** (ส่งรูป `MrBuk_QR_Give_1pt.png` ให้สแกนรับแต้มในบัตร LINE) + **บอทเก็บเศษ `450 บาท` ผูกกับบัญชี LINE ไว้ทบกับบิลถัดไปอัตโนมัติ** (ซื้อเพิ่มอีกเพียง 50 บาทในรอบหน้าจะครบ 500 บาทและได้เพิ่มอีก 1 แต้มทันที)
       - สั่งถุงใหญ่ 1 กก. `490.-` (หรือเก็บปลายทาง `530.-` หักค่าส่ง `40.-` เหลือ `490.-`) $\rightarrow$ **ไม่อนุโลมแต้มในบิลแรก (`0 แต้ม`)** แต่ **บอทบันทึกยอดสะสม `490 บาท` ผูกกับบัญชี LINE ไว้ทบกับบิลถัดไปอัตโนมัติ** (ขาดอีกเพียง 10 บาทในรอบหน้าก็จะครบ 500 บาทและรับ 1 แต้มทันที)
     - **สะสมครบ 5 แต้ม:** รับคูปองแลกฟรี! ข้าวบุกหอมมะลิซองเล็ก `60 กรัม` จำนวน `3 ซอง` (มูลค่า 132.-) — *จัดส่งพร้อมออเดอร์ถัดไปใน LINE*
     - **สะสมครบ 10 แต้ม:** รับคูปองแลกฟรี! ข้าวบุกหอมมะลิถุงกลาง `500 กรัม` จำนวน `1 ถุง` (มูลค่า 249.-) — *จัดส่งพร้อมออเดอร์ถัดไปใน LINE*
   - **คูปองต้อนรับเพื่อนใหม่ VIP ลด 5% (`MRBUKVIP5`):** ลดทันที 5% ทุกโปรโมชั่นสำหรับการสั่งซื้อใน LINE OA (1 กก. `490.-` เหลือ `465.-`, เซ็ตคู่ 41 มื้อ `950.-` เหลือ `902.-`, เซ็ต 30 ซอง `1,190.-` เหลือ `1,130.-`, เซ็ตใหญ่ 5 กก. `2,390.-` เหลือ `2,270.-`)
   - **Rich Menu (6 ปุ่ม) & ข้อความตอบกลับอัตโนมัติ (Auto-Response):** ตั้งค่าดักจับคีย์เวิร์ด `รับแต้ม`, `สะสมแต้ม`, `เช็กแต้ม`, `บัตรสะสมแต้ม`, `แลกแต้ม`, `รับสิทธิ์ลด 5%`, `ส่วนลด 5%`, `คูปองส่วนลด`, `MRBUKVIP5` ใน LINE OA Manager เรียบร้อยแล้วค่ะ
   - **ภาพ QR Code แจกแต้มแบบไม่มีวันหมดอายุ (Non-Expiring Point QR Codes):** บันทึกไว้ที่ `D:\MrBuk Content\Mr buk line oa\` ครบ 3 ระดับ (`MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png`) พร้อมระบบกันสแกนซ้ำของ LINE OA (สแกนรับแต้มได้สูงสุดวันละ 1 ครั้งต่อ 1 บัญชี)
   - **ไฟล์ใบแนบกล่องพัสดุ A5 สำหรับส่งโรงพิมพ์ (`D:\MrBuk print A5\300ppi\MrBuk print A5.jpg`):** ทำเสร็จเรียบร้อยแล้วค่ะ
2. **แผนการตลาด & ตาราง Broadcast LINE OA มิสเตอร์บุก (สำหรับฐานลูกค้า 500 คนแรก) + เอกสาร A4 แนวตั้งตัวใหญ่พิเศษ (ไม่เกิน 15 บรรทัด/หน้า):**
   - **กลยุทธ์ความถี่และสัดส่วนเนื้อหา (`40 : 30 : 30`):**
     - ส่ง Broadcast เพียง **สัปดาห์ละ 2 ครั้ง** (รวมเดือนละ 8 ครั้ง / ครั้งละ 1 รูป + 1 ข้อความสั้น ไม่เกิน 2 บับเบิล / เวลา `11:30 น.` หรือ `19:00 น.`) เพื่อไม่ให้ลูกค้ารำคาญหรือกดบล็อก
     - **40% สร้างความสัมพันธ์ (สัปดาห์ละ 1 ครั้ง):** แชร์ทริคชงข้าวบุกอัตราส่วน `1 : 1.5`, ทริค Meal Prep แช่ตู้เย็นเวฟ 1 นาที, และไอเดียเมนูอาหารตามสั่งแคลต่ำ เพื่อให้ลูกค้าหยิบข้าวบุกมาทานทุกวันจนหมดไวและกลับมาซื้อซ้ำไวขึ้น
     - **30% กระตุ้นบัตรสะสมแต้ม & ทวงเศษเงินสะสมใน LINE (เดือนละ 2 ครั้ง):** แจ้งเตือนลูกค้าที่มีเศษสะสม `450 บาท` (จากเซ็ตคู่ `950.-`) หรือ `490 บาท` (จากถุง 1 กก. `490.-`) ให้สั่งเติมสต็อกใน LINE เพื่อทบยอดรับแต้มทันที (เช่น จับคู่ถุง 1 กก. `490.-` + ซอง 60g `44.-` = `534 บาท` โอนส่งฟรีและได้ 1 แต้มทันที)
     - **30% โปรโมชั่นปิดการขาย (เดือนละ 2 ครั้ง — ต้นเดือน & สิ้นเดือน):** คูปองเฉพาะเพื่อนใน LINE ลด 5% (`MRBUKVIP5`) และโปรเซ็ตใหญ่คุ้มยกครัว 5 กก. แถมกล่องแก้ว
   - **ไฟล์เอกสารแผนการตลาด A4 แนวตั้ง (จัดหน้าไม่เกิน 15 บรรทัดต่อหน้า ตัวหนังสือใหญ่อ่านง่าย และอยู่ในกรอบ A4 100% ไม่ล้นขอบ):**
     - 📄 **ไฟล์ PDF ฉบับสมบูรณ์ (6 หน้า):**
       - [`D:\MrBuk Content\Mr buk line oa\แผนการตลาด_LINE_OA_มิสเตอร์บุก_A4_ฉบับสมบูรณ์.pdf`](file:///D:/MrBuk%20Content/Mr%20buk%20line%20oa/%E0%B9%81%E0%B8%9C%E0%B8%99%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B8%95%E0%B8%A5%E0%B8%B2%E0%B8%94_LINE_OA_%E0%B8%A1%E0%B8%B4%E0%B8%AA%E0%B9%80%E0%B8%95%E0%B8%AD%E0%B8%A3%E0%B9%8C%E0%B8%9A%E0%B8%B8%E0%B8%81_A4_%E0%B8%89%E0%B8%9A%E0%B8%B1%E0%B8%9A%E0%B8%AA%E0%B8%A1%E0%B8%9A%E0%B8%B9%E0%B8%A3%E0%B8%93%E0%B9%8C.pdf)
       - [`D:\MrBuk Content\Mr buk line oa\แผนการตลาด_LINE_OA_มิสเตอร์บุก_A4_ตัวใหญ่พิเศษ.pdf`](file:///D:/MrBuk%20Content/Mr%20buk%20line%20oa/%E0%B9%81%E0%B8%9C%E0%B8%99%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B8%95%E0%B8%A5%E0%B8%B2%E0%B8%94_LINE_OA_%E0%B8%A1%E0%B8%B4%E0%B8%AA%E0%B9%80%E0%B8%95%E0%B8%AD%E0%B8%A3%E0%B9%8C%E0%B8%9A%E0%B8%B8%E0%B8%81_A4_%E0%B8%95%E0%B8%B1%E0%B8%A7%E0%B9%83%E0%B8%AB%E0%B8%8D%E0%B9%88%E0%B8%9E%E0%B8%B4%E0%B9%80%E0%B8%A8%E0%B8%A9.pdf)
     - 🖼️ **ไฟล์รูปภาพ A4 แยกทีละหน้า (6 หน้า สำหรับส่งเข้าแชท LINE):** [`D:\MrBuk Content\Mr buk line oa\A4_Pages_แผนการตลาด_LINE_OA\`](file:///D:/MrBuk%20Content/Mr%20buk%20line%20oa/A4_Pages_%E0%B9%81%E0%B8%9C%E0%B8%99%E0%B8%81%E0%B8%B2%E0%B8%A3%E0%B8%95%E0%B8%A5%E0%B8%B2%E0%B8%94_LINE_OA) (`หน้า_1_แผน_LINE_OA_มิสเตอร์บุก_A4.png` ถึง `หน้า_6_แผน_LINE_OA_มิสเตอร์บุก_A4.png`)
     - 🐍 **สคริปต์ต้นฉบับสำหรับแก้ไข/สร้างไฟล์ A4 ใหม่ได้ตลอดเวลา:** [`D:\MrBuk Content\Mr buk line oa\generate_mrbuk_a4_plan.py`](file:///D:/MrBuk%20Content/Mr%20buk%20line%20oa/generate_mrbuk_a4_plan.py)
3. **อัปเดตไฟล์ความรู้และกฎเหล็กเฉพาะของ มิสเตอร์บุก ([`messenger-engine/config_mrbuk.json`](file:///D:/chat%20bot/messenger-engine/config_mrbuk.json)) ครบ 100% แล้ว:**
   - แก้ไขข้อมูลใน `config_mrbuk.json` ให้เป็นข้อมูลจริงของ **มิสเตอร์บุก (`Mr.Buk`)** ทั้งหมด (ไม่ปะปนกับข้าวบุกสุขใจ): สัดส่วนแป้งบุก 46% (ผงบุก 54%) + ข้าวหอมมะลิแท้ 44% + น้ำ 10%, พลังงาน 23 kcal / คาร์บ 5g, เลข อย. `13-4-06169-6-0001` + ฮาลาล, เลขบัญชีธนาคารกสิกรไทย `989-2-13624-3` (บจก. ทูเคพี อิควิปเม้นท์), ราคาจริงครบทั้ง 4 โปรโมชั่นหลัก (`44.-`, `249.-`, `490.-`, `599.-`, `1,190.-`, `950.-`, `2,390.-`), และเพิ่มบล็อก `loyalty_program` + FAQ กติกาการสะสมแต้มเฉพาะใน LINE `@misterbuk` เมื่อซื้อครบทุก 500 บาท (ไม่รวมค่าส่ง) พร้อมเก็บเศษเงินทบยอดเรียบร้อยแล้วค่ะ
4. **พัฒนาระบบสะสมแต้ม LINE OA แบบผูกบัญชี LINE โดยตรง + เก็บเศษเงินทบยอด + ป้องกันการเคลมบิลซ้ำ 100% (`app/loyalty.py` + `database.py` + `media_generator.py` + `jst_erp.py` + `audit.py` + `main.py`) เสร็จสมบูรณ์พร้อมใช้งานจริง:**
   - **สลับโหลด `config_mrbuk.json` อัตโนมัติตาม `brand_id == "mrbuk"`:** เพิ่ม `load_brand_config(brand_id)` ใน [`app/config_loader.py`](file:///D:/chat%20bot/messenger-engine/app/config_loader.py) และ `_get_brand_config_and_llm(brand_id)` ใน [`app/main.py`](file:///D:/chat%20bot/messenger-engine/app/main.py) ให้แบรนด์มิสเตอร์บุกใช้ข้อมูลสินค้า บัญชีกสิกรไทย `989-2-13624-3` และโปรโมชั่นของมิสเตอร์บุกแยกขาดจากข้าวบุกสุขใจ 100%
   - **ซิงก์รูป QR Code แจกแต้ม (`1pt`, `2pt`, `4pt`) เข้า `app/static/media/` อัตโนมัติ:** อัปเดต [`app/media_generator.py`](file:///D:/chat%20bot/messenger-engine/app/media_generator.py) ให้คัดลอกไฟล์ `MrBuk_QR_Give_1pt.png`, `MrBuk_QR_Give_2pt.png`, `MrBuk_QR_Give_4pt.png` จาก `D:\MrBuk Content\Mr buk line oa\` เข้า `app/static/media/` พร้อมฟังก์ชัน `get_mrbuk_qr_media_for_points(points)` แตกยอดแต้มเป็นชุดรูป QR (`4pt`, `2pt`, `1pt`) อัตโนมัติ
   - **ตารางฐานข้อมูลสะสมแต้มคู่ขนาน & กันเคลมบิลซ้ำ ([`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py)):**
     - `LoyaltyMember` (`loyalty_members`): เก็บ `line_user_id`, `phone`, `total_points`, `lifetime_points`, `lifetime_spend_thb`, **`carryover_thb` (ยอดเงินสะสมยกไปรอบหน้า)**, `pending_reward`, `redeemed_history` พร้อม Auto-Migration เพิ่มคอลัมน์ `carryover_thb` อัตโนมัติ
     - `LoyaltyClaimedOrder` (`loyalty_claimed_orders`): บันทึก `order_ref` (`JST:<order_id>` และ `CHAT:<psid>:<msg_id>` พร้อม `ALIAS:` ล็อกข้ามระบบ) ป้องกันการเคลมแต้มซ้ำจากบิลเดิม 100%
     - สำรองสมุดบัญชีแต้มและเศษเงินสะสมอัตโนมัติลงไฟล์ [`messenger-engine/reports/mrbuk_loyalty_ledger.json`](file:///D:/chat%20bot/messenger-engine/reports/mrbuk_loyalty_ledger.json) และ `.csv` ทุกครั้งที่มีการเคลื่อนไหว (`_sync_loyalty_ledger_snapshot`)
   - **โมดูลคำนวณแต้ม ผูกบัญชี LINE โดยตรง และแลกของแถม ([`app/loyalty.py`](file:///D:/chat%20bot/messenger-engine/app/loyalty.py)):**
     - ผูกยอดสั่งซื้อใน LINE OA `@misterbuk` จาก `line_user_id` ของลูกค้าในห้องแชทโดยตรง (`_extract_verified_orders_from_chatbot_db(..., line_user_id=line_user_id)`) **โดยที่ลูกค้าไม่ต้องพิมพ์เบอร์โทรศัพท์ 10 หลัก** (และยังรองรับการค้นหาด้วยเบอร์โทรหรือชื่อผู้รับเผื่อแอดมินเรียกใช้ผ่าน API ได้ด้วย)
     - กติกาคำนวณแต้มและเก็บเศษทบยอด (`extract_net_product_amount_thb` & `calculate_points_and_carryover`): หักค่าจัดส่ง/ค่าปลายทาง (`30`, `40`, `70` บาท) ออกก่อนเสมอ คิดจากยอดค่าสินค้าสุทธิครบทุก 500 บาท = 1 แต้ม (`490 บาท ไม่อนุโลม` ต้องครบ 500 บาทขึ้นไปเท่านั้น) พร้อมเก็บเศษยอดเงินที่เกินหรือยังไม่ครบ 500 บาท (`carryover_thb`) ไว้ในฐานข้อมูลของบอทเพื่อทบกับออเดอร์ถัดไปอัตโนมัติ
     - กติกาแลกของแถม (`redeem_loyalty_points`): ครบ **5 แต้ม** แลกฟรีซองเล็ก `60g × 3 ซอง` (มูลค่า 132.-) / ครบ **10 แต้ม** แลกฟรีถุงกลาง `500g × 1 ถุง` (มูลค่า 249.-) รับพร้อมออเดอร์ถัดไป
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
     - ส่งโค้ดชุดล่าสุดขึ้น `https://github.com/torithaimkt-tech/buksukjai-omnichannel.git` และย้ายเซิร์ฟเวอร์จริงมาอยู่ภายใต้อีเมล `buksukjai@gmail.com` (`Bukrice's workspace`, Service ID: `srv-dbpvo3h5efls7397humg`, URL: `https://buksukjai-omnichannel-twht.onrender.com`) แยกออกจาก `torithaimkt@gmail.com` (`Tori's workspace`) สำเร็จ 100%
  2. **✅ ระบบสำรองความจำแชทถาวรครบทุกช่องทาง 0 บาท (`/api/db/status`):**
     - อัปเกรด `save_persistent_snapshot()` และ `restore_persistent_snapshot_if_needed()` ใน [`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py) ให้จำครบทั้ง Facebook + LINE OA + LINE Group (รวม 183 ห้องแชท, 2,451 ข้อความ, และแต้มสะสม Loyalty) กู้คืนอัตโนมัติทันทีที่เซิร์ฟเวอร์ Render รีสตาร์ท
  3. **✅ ระบบต่ออายุคุกกี้ JST ERP อัตโนมัติ (`/api/jst/config`) & รายงานตรวจสุขภาพระบบทุกเช้า 07:00 น.:**
     - เพิ่ม Sliding Cookie Renewal ใน [`app/jst_erp.py`](file:///D:/chat%20bot/messenger-engine/app/jst_erp.py) และเพิ่มบล็อก **`🩺 เช็กสุขภาพระบบเช้านี้ (System Health Check)`** ต่อท้ายรายงานสรุปยอด 07:00 น. ใน [`app/daily_sheet_report.py`](file:///D:/chat%20bot/messenger-engine/app/daily_sheet_report.py)
  4. **✅ กำแพงกั้นข้อมูลข้ามแบรนด์ 100% (`_resolve_brand_config_path()` & ด่าน `3.0 Hard Cross-Brand Isolation Wall`):**
     - ล็อกให้แต่ละแบรนด์อ่านเฉพาะไฟล์ตั้งค่าของตัวเองใน [`app/prompt_engine.py`](file:///D:/chat%20bot/messenger-engine/app/prompt_engine.py) และ [`app/audit.py`](file:///D:/chat%20bot/messenger-engine/app/audit.py) ห้ามดึงโปรโมชันหรือเลขบัญชีของข้าวบุกสุขใจไปใช้เมื่อเปิดแบรนด์ใหม่เด็ดขาด
  5. **✅ ย้ายไฟล์ประวัติแชทดิบ 3 เพจมาเก็บในโฟลเดอร์ของฝั่งดิจิสท์ ฮับเรียบร้อยแล้ว:**
     - เก็บไว้ที่ `D:\buksukjai\chatbot-data\commentandmessage_3pages_raw` และ `D:\buksukjai\chatbot-data\customer_database_output_3pages`
  6. **✅ อัปเกรด PostgreSQL Driver (`psycopg2-binary`), Render Blueprint (`buksukjai-db`), สคริปต์นำเข้า n8n 4 โฟลว์, และล็อก LINE Webhook ของ `AIFY (@599fgktd)` บน Cloud ถาวร:**
     - รองรับทั้ง PostgreSQL (`_normalize_database_url` + `_build_engine` ใน [`app/database.py`](file:///D:/chat%20bot/messenger-engine/app/database.py)) และ SQLite Snapshot พร้อม Endpoint `/api/db/status` และ `/api/n8n/workflows`
     - ซิงก์ไฟล์เวิร์กโฟลว์ทั้ง 4 ตัวไปที่ [`D:\torimarketing\n8n-workflows\`](file:///D:/torimarketing/n8n-workflows/) + หน้ากระดาน [`amp_ads_config.json`](file:///D:/torimarketing/baantori-web/data/amp_ads_config.json) และสร้างสคริปต์คลิกเดียว [`import_and_start_n8n.bat`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/import_and_start_n8n.bat)
     - ผูก Token จริงของ `AIFY (@599fgktd)` ลงใน [`4_torimarketing_admin_bot.json`](file:///D:/chat%20bot/messenger-engine/n8n_workflows/4_torimarketing_admin_bot.json) และล็อก LINE Webhook Endpoint ไปที่ `https://buksukjai-omnichannel.onrender.com/webhook/line/aify` (`active: True`) ป้องกันไม่ให้ Tunnel ชั่วคราวในเครื่องเขียนทับเมื่อปิดคอมพิวเตอร์ค่ะ

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
  - เพื่อให้กดดูผังเชื่อมโหนดและไฟล์เวิร์กโฟลว์ n8n ทั้ง 4 ตัวได้จากหน้าเว็บ `https://buksukjai-omnichannel-twht.onrender.com/` โดยตรง

### 📝 แม่แบบ 6 ข้อสำหรับสั่งเปิดแบรนด์ใหม่ครั้งต่อไป (Brand Onboarding Template)
เมื่อคุณนัดต้องการเพิ่มแบรนด์ใหม่เข้าสู่ระบบ Flow ที่เสถียรแล้ว เพียงแจ้งข้อมูล 6 ข้อนี้ในแชทใหม่ได้เลยค่ะ:
1. **ชื่อแบรนด์และรหัสแบรนด์ (`brand_id`):** เช่น `luluna`, `sopure`, `mrbuk`
2. **รายการสินค้า ราคา โปรโมชัน และค่าจัดส่ง:** โอนส่งฟรีที่ยอดเท่าไหร่ / เก็บปลายทางบวกเพิ่มเท่าไหร่
3. **เลขบัญชีธนาคารรับโอนของแบรนด์นั้น:** ชื่อธนาคาร เลขบัญชี และชื่อบัญชี (ระบบจะล็อกด่านตรวจห้ามหลุดเลขบัญชีอื่น 100%)
4. **คำถามที่พบบ่อย (FAQ) 5–10 ข้อ:** เช่น วิธีทาน อายุการเก็บรักษา เลข อย. ลิงก์ Shopee/TikTok
5. **รูปตารางโปรโมชันของแบรนด์นั้น:** สำหรับให้บอทส่งรูปอัตโนมัติเมื่อลูกค้าถามราคา
6. **รหัสเพจและกุญแจเชื่อมต่อ (Page ID & Access Token):** ของ Facebook Page และ/หรือ LINE OA ของแบรนด์นั้นค่ะ
