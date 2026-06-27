import type { Message } from "@/types";

export interface Suggestion {
    icon: string;
    title: string;
    desc: string;
    prompt: string;
}

export const SUGGESTIONS = {
    th: [
        // Coding & Tech
        { icon: "Code", title: "เขียนโค้ด", desc: "ช่วยเขียนและรีแฟคเตอร์โค้ด", prompt: "เขียนฟังก์ชัน Python สำหรับดึงข้อมูลจาก API แบบ Async" },
        { icon: "Wrench", title: "แก้ปัญหา", desc: "ช่วยวิเคราะห์และแก้ไขปัญหา", prompt: "ช่วยหาบั๊กในโค้ด React นี้ให้หน่อย: useEffect มันรันวนลูบไม่หยุด" },
        { icon: "Palette", title: "ออกแบบ UI", desc: "ขอไอเดียออกแบบหน้าเว็บ", prompt: "ขอไอเดียออกแบบ Dashboard สำหรับดูยอดขายสไตล์ Minimal" },
        { icon: "Atom", title: "React Hooks", desc: "อธิบายการใช้งาน Hooks", prompt: "อธิบายความแตกต่างระหว่าง useMemo และ useCallback แบบเข้าใจง่ายๆ" },
        { icon: "Box", title: "Docker", desc: "เขียน Dockerfile", prompt: "เขียน Dockerfile สำหรับโปรเจค Node.js Express ให้หน่อย" },

        // Writing & Content
        { icon: "FileText", title: "เขียนบทความ", desc: "ช่วยร่างบทความน่าสนใจ", prompt: "ช่วยร่างโครงสร้างบทความเกี่ยวกับ 'อนาคตของ AI ในปี 2025'" },
        { icon: "Mail", title: "เขียนอีเมล", desc: "ร่างอีเมลติดต่องาน", prompt: "เขียนอีเมลขอลางาน 2 วัน เป็นภาษาอังกฤษแบบทางการ" },
        { icon: "Megaphone", title: "Caption", desc: "คิดแคปชั่นขายของ", prompt: "คิดแคปชั่น Facebook ขายครีมกันแดด เน้นตลกๆ หน่อย" },
        { icon: "FileSearch", title: "สรุปงาน", desc: "สรุปรายงานการประชุม", prompt: "ช่วยสรุปรายงานการประชุมนี้ให้สั้น กระชับ และแยกเป็นหัวข้อ" },

        // Analysis & Planning
        { icon: "BarChart", title: "วิเคราะห์ข้อมูล", desc: "วิเคราะห์แนวโน้ม", prompt: "วิเคราะห์ข้อดีข้อเสียของการทำงานแบบ Remote Work ในปัจจุบัน" },
        { icon: "Plane", title: "วางแผนเที่ยว", desc: "จัดทริปเที่ยวให้หน่อย", prompt: "วางแผนเที่ยวญี่ปุ่น 5 วัน 4 คืน งบ 30,000 บาท เน้นกิน" },
        { icon: "Wallet", title: "วางแผนการเงิน", desc: "ขอคำแนะนำการออมเงิน", prompt: "ขอวิธีกระจายความเสี่ยงในการลงทุนสำหรับมือใหม่" },
        { icon: "ChefHat", title: "คิดเมนู", desc: "แนะนำเมนูอาหาร", prompt: "เย็นนี้กินอะไรดี? ขอเมนูง่ายๆ แคลอรี่ต่ำ สำหรับคนลดน้ำหนัก" },
        { icon: "Gift", title: "ไอเดียของขวัญ", desc: "หาของขวัญให้คนสำคัญ", prompt: "แนะนำของขวัญวันเกิดให้แฟนผู้ชาย ชอบเล่นเกม งบ 2000 บาท" },

        // Learning & Fun
        { icon: "Lightbulb", title: "ความรู้รอบตัว", desc: "ถามเรื่องน่าสนใจ", prompt: "ทำไมท้องฟ้าถึงเป็นสีฟ้า? อธิบายแบบวิทยาศาสตร์ง่ายๆ" },
        { icon: "Film", title: "แนะนำหนัง", desc: "หาหนังน่าดู", prompt: "แนะนำหนัง Sci-Fi หักมุมเจ๋งๆ ใน Netflix หน่อย" },
        { icon: "Music", title: "แต่งเพลง", desc: "ช่วยแต่งเนื้อเพลง", prompt: "ช่วยแต่งท่อนฮุคเพลงรักอกหัก สไตล์ R&B" },
        { icon: "Wind", title: "สุขภาพ", desc: "คำแนะนำสุขภาพ", prompt: "แนะนำท่ายืดเหยียดแก้ปวดหลังสำหรับคนนั่งทำงานนานๆ" },
    ],
    en: [
        // Coding & Tech
        { icon: "Code", title: "Write Code", desc: "Generate functions & scripts", prompt: "Write a Python script to scrape data from a website using BeautifulSoup" },
        { icon: "Wrench", title: "Debug", desc: "Fix bugs and potential issues", prompt: "Help me find the memory leak in this Node.js application" },
        { icon: "Palette", title: "UI Components", desc: "Design improved components", prompt: "Suggest a modern, accessible design for a date picker component" },
        { icon: "Cloud", title: "AWS Ops", desc: "Cloud infrastructure tasks", prompt: "Explain how to set up an S3 bucket with public read access using Terraform" },
        { icon: "Smartphone", title: "Mobile Dev", desc: "React Native / Flutter", prompt: "How do I implement push notifications in React Native?" },

        // Writing & Content
        { icon: "FileText", title: "Blog Post", desc: "Draft engaging content", prompt: "Draft an outline for a blog post about 'The Rise of Agentic AI'" },
        { icon: "Mail", title: "Email", desc: "Professional correspondence", prompt: "Write a polite follow-up email after a job interview" },
        { icon: "FileSearch", title: "Summarize", desc: "Condense long text", prompt: "Summarize this technical paper into 5 key bullet points" },
        { icon: "Theater", title: "Storytelling", desc: "Creative writing assistant", prompt: "Write a short story intro about a robot who discovers emotions" },

        // Analysis & Planning
        { icon: "BarChart", title: "Data Analysis", desc: "Interpret data trends", prompt: "Analyze the impact of remote work on urban real estate prices" },
        { icon: "Plane", title: "Travel Plan", desc: "Itineraries & tips", prompt: "Plan a 3-day itinerary for a focused art tour in Paris" },
        { icon: "ChefHat", title: "Meal Prep", desc: "Healthy eating plans", prompt: "Create a 3-day high-protein meal plan for a vegetarian" },
        { icon: "Target", title: "Marketing", desc: "Strategy & campaigns", prompt: "Propose 3 growth hacking strategies for a new SaaS product" },

        // Learning & Fun
        { icon: "Lightbulb", title: "Explain Like I'm 5", desc: "Simplify complex topics", prompt: "Explain Quantum Computing to a 5-year-old" },
        { icon: "Film", title: "Movies", desc: "Film recommendations", prompt: "Recommend 3 psychological thrillers similar to 'Inception'" },
        { icon: "Brain", title: "Trivia", desc: "Interesting facts", prompt: "Tell me a mind-blowing fact about the ocean" },
        { icon: "BookOpen", title: "Book Study", desc: "Literary analysis", prompt: "What are the main themes in '1984' by George Orwell?" },
    ]
};

export const FOLLOW_UPS = {
    th: [
        "อธิบายเพิ่มเติมหน่อย",
        "ช่วยยกตัวอย่างให้ดูหน่อย",
        "สรุปให้สั้นๆ หน่อย",
        "มีข้อดีข้อเสียอะไรบ้าง?",
        "ทำไมถึงเป็นแบบนั้น?",
        "มีวิธีอื่นอีกไหม?",
        "แปลเป็นภาษาอังกฤษให้หน่อย",
        "ขอรายละเอียดเชิงลึกกว่านี้"
    ],
    en: [
        "Tell me more about that",
        "Can you give me an example?",
        "Please summarize this",
        "What are the pros and cons?",
        "Why is that the case?",
        "Are there any alternatives?",
        "Translate this to Thai",
        "Explain in more detail"
    ]
};

export type SuggestionLanguage = keyof typeof FOLLOW_UPS;

/** Local title from first user message (M15/M33 — no Langflow). */
export function generateChatTitle(userPrompt: string): string {
  return userPrompt.substring(0, 30);
}

function suggestionLanguageFromStorage(): SuggestionLanguage {
  return localStorage.getItem("language") === "th" ? "th" : "en";
}

/**
 * M16/M33 — Static follow-up suggestions (Langflow HTTP removed).
 * Accepts optional App.tsx args; ignores history for now.
 * TODO: Hermes-backed suggestion prompt when available.
 */
export async function generateSuggestions(
  _history?: Message[],
  _userPrompt?: string,
  _lastResponse?: string,
  language: SuggestionLanguage = suggestionLanguageFromStorage(),
): Promise<string[]> {
  const pool = FOLLOW_UPS[language] ?? FOLLOW_UPS.en;
  return [...pool].sort(() => 0.5 - Math.random()).slice(0, 3);
}
