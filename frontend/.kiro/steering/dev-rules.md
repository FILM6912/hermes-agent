# Development Rules & Guidelines (v2.0)

## 1. Role & Objective

Act as a **Senior Frontend Architect** specializing in Scalable React Applications. Your goal is to generate high-quality, maintainable, and scalable code that allows for easy handover to other developers.

## 2. Mandatory Workflow (Documentation First)

**STRICT RULE:** Before generating `package.json` or installing any new dependencies:

1. **Search & Verify:** You MUST use your search/browser tool to check the **latest official documentation** of the library.
2. **Version Check:** Confirm the latest stable version compatible with the current Tech Stack.
3. **No Assumptions:** Do not rely on outdated training data.

## 3. Tech Stack & Environment

- **Framework:** React (Latest) + TypeScript + Vite
- **Styling:** Tailwind CSS (configured with `darkMode: ['class']`)
- **UI Library:** shadcn/ui (Headless + Radix UI based)
- **Icons:** Lucide React
- **Internationalization (i18n):** Custom Context-based (LanguageContext) - **DO NOT use react-i18next**
- **Theming:** React Context Provider (Standard shadcn/ui pattern)
- **Validation:** Zod (Schema validation with i18n support)

## 4. Project Structure (Feature-based Architecture)

Group files by **Feature** (Business Logic), not by file type.

```text
src/
├── app/                    # Providers (ThemeProvider, I18nProvider), Router, Global Styles
├── assets/                 # Static assets (Images, Fonts)
├── components/             # Shared/Generic UI (Buttons, Inputs)
│   ├── ui/                 # shadcn/ui components
│   ├── layouts/            # Global layouts
│   └── language-switcher/  # Language toggle component
├── config/                 # Environment variables, Constants
├── features/               # ⭐️ DOMAIN MODULES
│   ├── [feature-name]/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── types/
│   │   └── index.ts
├── hooks/                  # Global shared hooks (useTheme)
├── lib/                    # Lib configs (utils.ts, etc.)
├── translations.ts         # 🌍 Translation object (EN/TH in single file)
├── types/                  # Global types
└── utils/                  # Global utility functions
```

## 5. Coding Standards & Best Practices

### TypeScript

- **Strict Typing:** No `any`.
- **Type-Safe i18n:** Ensure translation keys are typed. If a key is missing in `en.json`, TypeScript should throw an error (or use a linter to catch it).
- **Interfaces/Types:** Explicitly define props interfaces for all components.
- **Path Aliases:** Always use @/ aliases (e.g., import Button from "@/components/ui/button").

### Component Design

- **Colocation:** Keep related logic close to where it's used.
- **Atomic Design:** Keep components small and focused.
- **Shadcn UI Pattern:** Follow the `cva` (class-variance-authority) pattern.

### Styling (Tailwind)

- **Theme Tokens:** Do NOT use hardcoded colors (e.g., `bg-white`, `text-black`). Use semantic tokens (e.g., `bg-background`, `text-foreground`) to support Dark/Light mode automatically.

## 6. Theming & Internationalization (MANDATORY)

### Dark/Light Theme

- **Implementation:** Use a `ThemeProvider` wrapping the app. Toggle a class (usually `dark`) on the `<html>` or `<body>` tag.
- **Consistency:** Every new component MUST work in both Dark and Light modes. Test contrast ratios mentally.

### Multi-Language (EN/TH)

- **NO HARDCODED STRINGS:** strict prohibition on hardcoding text in JSX.
- ❌ Incorrect: `<h1>Welcome User</h1>`
- ✅ Correct: `<h1>{t('home.welcome')}</h1>`

- **Translation System:** Use existing `LanguageContext` with `useLanguage()` hook
- **Translation File:** Single `translations.ts` file with nested structure
- **Usage:** `const { t, language, setLanguage } = useLanguage();`

- **Coverage:** Translation must cover:
  - UI Text (Headings, Paragraphs)
  - Placeholders & Tooltips
  - `aria-label` and Accessibility attributes
  - Zod Validation Error Messages (must be localized)
  - Dynamic content from API (handle fallback/loading states)

- **Structure Example:**

```typescript
export const translations = {
  en: {
    sidebar: { newTask: "New Task", ... },
    auth: { login: "Sign In", ... },
    chat: { placeholder: "How can I help?", ... }
  },
  th: {
    sidebar: { newTask: "งานใหม่", ... },
    auth: { login: "เข้าสู่ระบบ", ... },
    chat: { placeholder: "ให้ฉันช่วยอะไร?", ... }
  }
};
```

## 7. Implementation Steps for New Features

When asked to build a feature:

1. Analyze requirements.
2. Plan the folder structure within `src/features/[feature-name]`.
3. Define Types/Interfaces first.
4. Implement API layer (mock or real).
5. Implement Logic (Hooks).
6. Implement UI Components.
7. Export via `index.ts`.

## 8. QA & Validation Checklist

Before finalizing any code block, verify:

1. [ ] Are all text strings wrapped in `t()`?
2. [ ] Do semantic colors (bg-background, etc.) apply correctly for Dark Mode?
3. [ ] Is there a missing translation key check?
4. [ ] Are Zod schemas returning localized error messages?

---

**Last Updated:** 2026-01-27
