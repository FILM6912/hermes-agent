# Frontend Refactoring Design

## Overview

This design document outlines the technical approach for refactoring the frontend codebase from a file-type-based structure to a feature-based architecture while preserving the existing translation system and functionality.

## Architecture Design

### Current Structure (File-Type Based)

```
src/
├── components/          # All components mixed together
├── hooks/              # All hooks
├── services/           # API services
├── types/              # All types
└── translations.ts
```

### Target Structure (Feature-Based)

```
src/
├── app/
│   └── providers.tsx
├── components/         # Shared UI only
│   ├── ui/
│   └── layouts/
├── features/
│   ├── auth/
│   ├── chat/
│   ├── settings/
│   ├── sidebar/
│   └── preview/
├── hooks/             # Global hooks (useTheme, useLanguage)
├── lib/
├── translations.ts    # Unchanged
├── types/             # Global types only
└── utils/
```

## Feature Modules Design

### 1. Auth Feature (`features/auth/`)

**Purpose:** Handle authentication UI and logic

**Structure:**

```
features/auth/
├── components/
│   └── AuthPage.tsx
├── types/
│   └── index.ts
└── index.ts
```

**Components:**

- `AuthPage`: Login/Signup form component

**Exports (index.ts):**

```typescript
export { AuthPage } from "./components/AuthPage";
export type * from "./types";
```

### 2. Chat Feature (`features/chat/`)

**Purpose:** Handle chat interface, messages, and AI communication

**Structure:**

```
features/chat/
├── api/
│   └── geminiService.ts
├── components/
│   ├── ChatInterface.tsx
│   ├── CodeBlock.tsx
│   ├── MessageList.tsx
│   └── MessageInput.tsx
├── hooks/
│   └── useChatLogic.ts (optional)
├── types/
│   └── index.ts
└── index.ts
```

**Components:**

- `ChatInterface`: Main chat container
- `CodeBlock`: Code rendering with preview
- `MessageList`: Message display logic
- `MessageInput`: Input area with attachments

**API:**

- `geminiService`: AI API communication

**Types:**

- `Message`, `Attachment`, `MessageVersion`

**Exports (index.ts):**

```typescript
export { ChatInterface, CodeBlock } from "./components/ChatInterface";
export {
  streamMessageFromGemini,
  generateChatTitle,
} from "./api/geminiService";
export type * from "./types";
```

### 3. Settings Feature (`features/settings/`)

**Purpose:** Application settings and configuration

**Structure:**

```
features/settings/
├── components/
│   ├── SettingsView.tsx
│   └── tabs/
│       ├── GeneralTab.tsx
│       ├── AccountTab.tsx
│       ├── ToolsTab.tsx
│       ├── AgentTab.tsx
│       └── LangflowTab.tsx
├── types/
│   └── index.ts
└── index.ts
```

**Components:**

- `SettingsView`: Main settings container with sidebar
- Tab components: Separate components for each settings section

**Types:**

- `SettingsTab`, `AgentFlow`, `ProfileSettings`

**Exports (index.ts):**

```typescript
export { SettingsView } from "./components/SettingsView";
export type * from "./types";
```

### 4. Sidebar Feature (`features/sidebar/`)

**Purpose:** Navigation sidebar with chat history

**Structure:**

```
features/sidebar/
├── components/
│   └── Sidebar.tsx
├── types/
│   └── index.ts
└── index.ts
```

**Components:**

- `Sidebar`: Navigation and chat history

**Types:**

- `SidebarProps`

**Exports (index.ts):**

```typescript
export { Sidebar } from "./components/Sidebar";
export type * from "./types";
```

### 5. Preview Feature (`features/preview/`)

**Purpose:** Preview window and process steps

**Structure:**

```
features/preview/
├── components/
│   ├── PreviewWindow.tsx
│   └── ProcessStep.tsx
├── types/
│   └── index.ts
└── index.ts
```

**Components:**

- `PreviewWindow`: HTML preview panel
- `ProcessStep`: Process step visualization

**Types:**

- `ProcessStep`

**Exports (index.ts):**

```typescript
export { PreviewWindow, ProcessStep } from "./components";
export type * from "./types";
```

## Shared Components Design

### Components Directory (`src/components/`)

**Purpose:** Truly shared/generic UI components

**Contents:**

- `ErrorModal.tsx` - Error display modal
- `LangFlowConfigModal.tsx` - LangFlow configuration
- `ElectronFileManager.tsx` - Electron file operations
- `ui/` - shadcn/ui components (if any)
- `layouts/` - Global layout components

## Global Hooks Design

### `src/hooks/`

**Purpose:** Application-wide hooks

**Contents:**

- `useLanguage.tsx` - Translation hook (unchanged)
- `useTheme.tsx` - Theme management hook
- `useElectron.ts` - Electron integration hook

## Type System Design

### Global Types (`src/types/index.ts`)

**Purpose:** Types used across multiple features

**Contents:**

```typescript
export type AIProvider = "google" | "openai";
export type Language = "en" | "th";

export interface ModelConfig {
  provider: AIProvider;
  baseUrl: string;
  modelId: string;
  name: string;
  mcpServers?: string[];
  enabledConnections?: string[];
  enabledModels?: string[];
  systemPrompt?: string;
  voiceDelay?: number;
  langflowUrl?: string;
  langflowApiKey?: string;
}

export interface ChatSession {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}

export interface FileNode {
  name: string;
  type: "file" | "folder";
  children?: FileNode[];
}
```

### Feature-Specific Types

Each feature defines its own types in `features/[feature]/types/index.ts`

## Translation System Design

### Preservation Strategy

**NO CHANGES** to the existing translation system:

1. **Keep `src/translations.ts`** - Exact same structure
2. **Keep `src/hooks/useLanguage.tsx`** - No modifications
3. **Keep `LanguageProvider`** - Same implementation
4. **Keep `t()` function usage** - All components continue using it

**Example (unchanged):**

```typescript
const { t, language, setLanguage } = useLanguage();
<h1>{t('auth.welcomeBack')}</h1>
```

## Theming Design

### Semantic Color Tokens

Replace hardcoded colors with semantic tokens:

**Before:**

```tsx
className = "bg-white dark:bg-black text-zinc-900 dark:text-white";
```

**After:**

```tsx
className = "bg-background text-foreground";
```

### Theme Configuration

Configure in `tailwind.config.js`:

```javascript
module.exports = {
  darkMode: ["class"],
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        // ... other semantic tokens
      },
    },
  },
};
```

## Import Strategy

### Path Aliases

All imports use `@/` prefix:

```typescript
// Feature imports
import { ChatInterface } from "@/features/chat";
import { Sidebar } from "@/features/sidebar";
import { SettingsView } from "@/features/settings";

// Shared component imports
import { ErrorModal } from "@/components/ErrorModal";

// Hook imports
import { useLanguage } from "@/hooks/useLanguage";
import { useTheme } from "@/hooks/useTheme";

// Type imports
import type { ModelConfig, ChatSession } from "@/types";
```

### Configuration

Update `tsconfig.json`:

```json
{
  "compilerOptions": {
    "baseUrl": ".",
    "paths": {
      "@/*": ["src/*"]
    }
  }
}
```

Update `vite.config.ts`:

```typescript
export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

## Migration Strategy

### Phase 1: Setup Structure

1. Create feature directories
2. Create index.ts files for exports
3. Update path alias configuration

### Phase 2: Move Files

1. Move components to feature folders
2. Update imports in moved files
3. Update exports in index.ts files

### Phase 3: Update Imports

1. Update App.tsx imports
2. Update cross-feature imports
3. Verify all imports resolve correctly

### Phase 4: Cleanup

1. Remove old empty directories
2. Verify no broken imports
3. Test all features

## Component Refactoring Details

### ChatInterface Refactoring

**Current:** Single large file (1563 lines)

**Strategy:**

1. Keep main `ChatInterface` component
2. Extract `CodeBlock` to separate file
3. Consider extracting message rendering logic
4. Keep all functionality intact

**File Split:**

```
features/chat/components/
├── ChatInterface.tsx (main container)
├── CodeBlock.tsx (code rendering)
├── MessageList.tsx (optional - message display)
└── MessageInput.tsx (optional - input area)
```

### SettingsView Refactoring

**Current:** Single large file (1678 lines)

**Strategy:**

1. Keep main `SettingsView` container
2. Extract each tab to separate component
3. Share state through props

**File Split:**

```
features/settings/components/
├── SettingsView.tsx (container + sidebar)
└── tabs/
    ├── GeneralTab.tsx
    ├── AccountTab.tsx
    ├── ToolsTab.tsx
    ├── AgentTab.tsx
    └── LangflowTab.tsx
```

## Testing Strategy

### Verification Checklist

- [ ] All features render correctly
- [ ] Dark/Light mode works
- [ ] Language switching works (EN/TH)
- [ ] Chat functionality works
- [ ] Settings save correctly
- [ ] Authentication works
- [ ] Preview window works
- [ ] No console errors
- [ ] All imports resolve
- [ ] TypeScript compiles without errors

## Risk Mitigation

### Potential Issues

1. **Import Resolution:** Path aliases may not work immediately
   - **Mitigation:** Test imports after configuration changes

2. **Circular Dependencies:** Features importing each other
   - **Mitigation:** Use global types for shared interfaces

3. **Type Errors:** Moving types may break imports
   - **Mitigation:** Move types first, then components

4. **Runtime Errors:** Broken imports at runtime
   - **Mitigation:** Test each feature after migration

## Rollback Plan

If critical issues occur:

1. Revert to previous commit
2. Fix issues in isolated branch
3. Re-apply changes incrementally

## Success Metrics

- ✅ All components organized by feature
- ✅ Zero TypeScript errors
- ✅ Zero console errors
- ✅ All features functional
- ✅ Dark/Light mode working
- ✅ Translation system working
- ✅ Clean import structure
- ✅ No relative imports (../)

## Correctness Properties

### Property 1: Import Resolution

**Validates: Requirements 5.1, 5.2**

**Property:** All imports using @/ alias resolve correctly

```typescript
// For all files in src/
// All imports starting with @/ must resolve to valid modules
```

**Test Strategy:**

- Run TypeScript compiler
- Check for module resolution errors
- Verify no 404 errors in browser console

### Property 2: Feature Isolation

**Validates: Requirements 1.1, 1.2, 4.1-4.4**

**Property:** Each feature is self-contained with proper exports

```typescript
// For each feature in features/
// Must have: components/, types/, index.ts
// index.ts must export all public APIs
```

**Test Strategy:**

- Verify folder structure
- Check index.ts exports
- Ensure no direct imports from feature internals

### Property 3: Translation Preservation

**Validates: Requirements 3.1, 3.2, 3.3**

**Property:** Translation system remains unchanged

```typescript
// useLanguage hook signature unchanged
// translations.ts structure unchanged
// All t() calls work correctly
```

**Test Strategy:**

- Compare useLanguage.tsx before/after
- Compare translations.ts before/after
- Test language switching in UI

### Property 4: Theme Consistency

**Validates: Requirements 2.1, 2.2**

**Property:** All components use semantic color tokens

```typescript
// No hardcoded colors like bg-white, bg-black
// All use bg-background, text-foreground, etc.
```

**Test Strategy:**

- Search codebase for hardcoded colors
- Test dark/light mode switching
- Visual inspection of all pages

### Property 5: Functionality Preservation

**Validates: All requirements**

**Property:** All existing features work without regression

```typescript
// Chat sends messages correctly
// Settings save correctly
// Auth works correctly
// Preview renders correctly
```

**Test Strategy:**

- Manual testing of all features
- Check localStorage persistence
- Verify API calls work
- Test file uploads/attachments

## Notes

- This is a structural refactoring, not a feature addition
- Focus on organization and maintainability
- Preserve all existing functionality
- No UI/UX changes
- Keep translation system exactly as-is
