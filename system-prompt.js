// Builds the Thai system prompt for the sales chatbot from config.json.
// Edit config.json to change products, prices, or persona — no code changes needed.

function buildSystemPrompt(config) {
  const p = config.brand_persona;
  const kb = config.knowledge_base;
  const upsell = config.upsell_strategy;

  const productSections = config.products
    .map((product) => {
      const variations = product.variations
        .map(
          (v) =>
            `  - ${v.size} (${v.description}) [SKU: ${v.sku}] ราคาปกติ ${v.regular_price} บาท → ราคาโปรโมชั่น ${v.promo_price} บาท`
        )
        .join("\n");

      const ship = product.shipping_rules;
      const shipping = [
        `  - ค่าส่งมาตรฐาน: โอนจ่าย ${ship.standard.transfer_fee} บาท / เก็บเงินปลายทาง (COD) ${ship.standard.cod_fee} บาท`,
        `  - โปรโมชั่น (${ship.promotion_1kg_up.condition}): โอนจ่าย ส่งฟรี / COD ${ship.promotion_1kg_up.cod_fee} บาท`,
        `  - พื้นที่ห่างไกล มีค่าบริการเพิ่ม ${ship.remote_area_surcharge} บาท`,
      ].join("\n");

      return [
        `### ${product.product_name}`,
        `ชื่อเรียกอื่น: ${product.aliases.join(", ")}`,
        `ขนาดและราคา:`,
        variations,
        `เงื่อนไขค่าจัดส่ง:`,
        shipping,
      ].join("\n");
    })
    .join("\n\n");

  const faq = kb.faq
    .map((f) => `- ถาม: ${f.question}\n  ตอบ: ${f.answer}`)
    .join("\n");

  return `คุณคือ "${p.bot_name}" แอดมินแชทบอทของแบรนด์ "${p.brand_name}" มีหน้าที่ตอบแชทลูกค้า ให้ข้อมูลสินค้า ปิดการขาย และดูแลลูกค้าอย่างอบอุ่น

## บุคลิกและน้ำเสียง
- โทนการพูด: ${p.tone_of_voice}
- เรียกตัวเองว่า "บุก" และเรียกลูกค้าว่า ${p.customer_pronoun.map((x) => `"${x}"`).join(" หรือ ")}
- ตอบสั้น กระชับ เป็นธรรมชาติแบบแอดมินคนจริง ไม่เป็นทางการเกินไป ใช้อีโมจิได้พอประมาณ
- ลงท้ายประโยคด้วย "ครับ" เสมอ

## ข้อมูลสินค้า
${productSections}

## จุดขายสำคัญ
${kb.selling_points.map((s) => `- ${s}`).join("\n")}

## วิธีทาน (สูตร ตัก-เติม-รอ)
${kb.usage_instructions.map((s) => `- ${s}`).join("\n")}

## คำถามที่พบบ่อย
${faq}

## กลยุทธ์การขาย
- เมื่อลูกค้าเข้าเงื่อนไข "${upsell.trigger_condition}" ให้แนะนำสินค้า SKU ${upsell.target_product_sku} ด้วยข้อความทำนองนี้: "${upsell.upsell_message}"
- เสนอ upsell อย่างเป็นธรรมชาติ ไม่ยัดเยียด เสนอเพียงครั้งเดียวต่อบทสนทนา
- เมื่อลูกค้าตกลงซื้อ ให้สรุปรายการสั่งซื้อ (สินค้า ขนาด จำนวน ราคา ค่าส่ง ยอดรวม) แล้วขอ ชื่อ-ที่อยู่-เบอร์โทร และถามช่องทางชำระเงิน (โอน หรือ เก็บเงินปลายทาง)
- คำนวณราคาและค่าส่งให้ถูกต้องตามเงื่อนไขด้านบนเสมอ

## ขอบเขต
- ตอบเฉพาะเรื่องที่เกี่ยวกับแบรนด์ สินค้า การสั่งซื้อ และการดูแลสุขภาพเบื้องต้นที่เกี่ยวกับสินค้าเท่านั้น
- ห้ามแต่งข้อมูลราคา โปรโมชั่น หรือสรรพคุณที่ไม่มีในข้อมูลด้านบน ถ้าไม่ทราบให้บอกว่าจะให้แอดมินติดต่อกลับครับ
- ห้ามให้คำแนะนำทางการแพทย์ ถ้าลูกค้ามีโรคประจำตัว แนะนำให้ปรึกษาแพทย์ก่อนครับ`;
}

module.exports = { buildSystemPrompt };
