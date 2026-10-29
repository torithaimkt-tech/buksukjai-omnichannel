const fs = require("fs");
const path = require("path");
const express = require("express");
const OpenAI = require("openai");
const { buildSystemPrompt } = require("./system-prompt");

// Load .env if present (no dependency needed)
const envPath = path.join(__dirname, ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([\w.]+)\s*=\s*(.*)\s*$/);
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
}

const config = JSON.parse(fs.readFileSync(path.join(__dirname, "config.json"), "utf8"));
const SYSTEM_PROMPT = buildSystemPrompt(config);

const app = express();
app.use(express.json());
app.use(express.static(path.join(__dirname, "public")));

const MODEL = process.env.OPENAI_MODEL || "gpt-4o-mini";
// Fall back to a placeholder so the server can start without a key — the
// /api/chat handler below checks OPENAI_API_KEY itself and returns a
// friendly error before ever issuing a real request.
const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY || "not-set" });

// Frontend fetches greeting + bot name from config
app.get("/api/config", (_req, res) => {
  res.json({
    brand_name: config.brand_persona.brand_name,
    bot_name: config.brand_persona.bot_name,
    greeting_message: config.brand_persona.greeting_message,
  });
});

app.post("/api/chat", async (req, res) => {
  if (!process.env.OPENAI_API_KEY) {
    return res.status(500).json({
      error:
        "ยังไม่ได้ตั้งค่า OPENAI_API_KEY — สร้างไฟล์ .env ในโฟลเดอร์โปรเจกต์ แล้วใส่ OPENAI_API_KEY=sk-...",
    });
  }

  const { messages } = req.body;
  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: "messages ต้องเป็น array ที่ไม่ว่าง" });
  }

  try {
    const response = await client.chat.completions.create({
      model: MODEL,
      max_tokens: 1024,
      messages: [
        { role: "system", content: SYSTEM_PROMPT },
        ...messages.map((m) => ({
          role: m.role === "assistant" ? "assistant" : "user",
          content: String(m.content),
        })),
      ],
    });

    const reply = response.choices[0]?.message?.content ?? "";
    res.json({ reply });
  } catch (error) {
    if (error instanceof OpenAI.AuthenticationError) {
      res.status(500).json({ error: "API key ไม่ถูกต้อง กรุณาตรวจสอบ OPENAI_API_KEY" });
    } else if (error instanceof OpenAI.RateLimitError) {
      res.status(429).json({ error: "มีการใช้งานหนาแน่น กรุณาลองใหม่อีกครั้งในสักครู่ครับ" });
    } else if (error instanceof OpenAI.APIError) {
      console.error("API error:", error.status, error.message);
      res.status(500).json({ error: "เกิดข้อผิดพลาดจากระบบ AI กรุณาลองใหม่อีกครั้งครับ" });
    } else {
      console.error("Unexpected error:", error);
      res.status(500).json({ error: "เกิดข้อผิดพลาดที่ไม่คาดคิด กรุณาลองใหม่อีกครั้งครับ" });
    }
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`ข้าวบุกสุขใจ chatbot: http://localhost:${PORT}`);
  if (!process.env.OPENAI_API_KEY) {
    console.warn("⚠ OPENAI_API_KEY is not set — chat requests will fail until you set it (see README.md)");
  }
});
