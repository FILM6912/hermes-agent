# Frontend Refactoring Requirements

## Feature Overview

Refactor the existing React + TypeScript frontend application to follow feature-based architecture as defined in the development rules, while maintaining the existing translation system (LanguageContext).

## User Stories

### 1. As a developer, I want the codebase organized by features

**Acceptance Criteria:**

- 1.1 All business logic is grouped by feature domain (auth, chat, settings, sidebar, preview)
- 1.2 Each feature has its own folder with api/, components/, hooks/, and types/ subfolders
- 1.3 Shared/generic UI components remain in src/components/
- 1.4 Feature exports are centralized through index.ts files

### 2. As a developer, I want consistent theming support

**Acceptance Criteria:**

- 2.1 All components use semantic color tokens (bg-background, text-foreground) instead of hardcoded colors
- 2.2 Dark/Light mode works correctly across all components
- 2.3 Theme provider is properly configured in app/providers.tsx

### 3. As a developer, I want the existing translation system preserved

**Acceptance Criteria:**

- 3.1 Current LanguageContext implementation remains unchanged
- 3.2 All text strings continue using t() function
- 3.3 translations.ts file structure is maintained
- 3.4 No migration to react-i18next or other i18n libraries

### 4. As a developer, I want proper separation of concerns

**Acceptance Criteria:**

- 4.1 API calls are isolated in feature/api/ folders
- 4.2 Business logic hooks are in feature/hooks/ folders
- 4.3 Feature-specific components are in feature/components/ folders
- 4.4 Type definitions are in feature/types/ folders

### 5. As a developer, I want clean imports using path aliases

**Acceptance Criteria:**

- 5.1 All imports use @/ alias (e.g., @/features/chat/components/ChatMessage)
- 5.2 No relative imports like ../../../
- 5.3 Path aliases are configured in tsconfig.json and vite.config.ts

## Technical Requirements

### Architecture

- Follow feature-based architecture (not file-type based)
- Maintain existing functionality without breaking changes
- Keep current routing structure
- Preserve all existing features (chat, auth, settings, preview, sidebar)

### File Structure

```
src/
├── app/                    # Providers, Router, Global Styles
│   └── providers.tsx       # ThemeProvider, LanguageProvider
├── assets/                 # Static assets
├── components/             # Shared/Generic UI only
│   ├── ui/                 # shadcn/ui components
│   └── layouts/            # Global layouts
├── config/                 # Environment variables, Constants
├── features/               # Domain modules
│   ├── auth/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── types/
│   │   └── index.ts
│   ├── chat/
│   │   ├── api/
│   │   ├── components/
│   │   ├── hooks/
│   │   ├── types/
│   │   └── index.ts
│   ├── settings/
│   ├── sidebar/
│   └── preview/
├── hooks/                  # Global shared hooks (useTheme, useLanguage)
├── lib/                    # Lib configs (utils.ts)
├── translations.ts         # Translation object (EN/TH)
├── types/                  # Global types
└── utils/                  # Global utility functions
```

### Components to Refactor

1. **Auth Feature**
   - AuthPage.tsx → features/auth/components/AuthPage.tsx
   - Auth types → features/auth/types/

2. **Chat Feature**
   - ChatInterface.tsx → features/chat/components/ChatInterface.tsx
   - CodeBlock component → features/chat/components/CodeBlock.tsx
   - Message components → features/chat/components/
   - geminiService.ts → features/chat/api/geminiService.ts
   - Chat types → features/chat/types/

3. **Settings Feature**
   - SettingsView.tsx → features/settings/components/SettingsView.tsx
   - Settings tabs → features/settings/components/tabs/
   - Settings types → features/settings/types/

4. **Sidebar Feature**
   - Sidebar.tsx → features/sidebar/components/Sidebar.tsx
   - Sidebar types → features/sidebar/types/

5. **Preview Feature**
   - PreviewWindow.tsx → features/preview/components/PreviewWindow.tsx
   - ProcessStep.tsx → features/preview/components/ProcessStep.tsx
   - Preview types → features/preview/types/

6. **Shared Components** (remain in src/components/)
   - ErrorModal.tsx
   - LangFlowConfigModal.tsx
   - ElectronFileManager.tsx

### Constraints

- **DO NOT** change the translation system (keep LanguageContext)
- **DO NOT** break existing functionality
- **DO NOT** change the UI/UX
- **DO NOT** modify package.json dependencies unless absolutely necessary
- **MUST** maintain backward compatibility
- **MUST** use semantic color tokens for theming

## Out of Scope

- Adding new features
- Changing translation system to react-i18next
- UI/UX redesign
- Performance optimization (unless critical)
- Adding new dependencies

## Success Criteria

- All components are organized by feature
- All imports use @/ path aliases
- All text uses t() translation function
- Dark/Light mode works correctly
- All existing features work without regression
- Code follows TypeScript strict mode
- No console errors or warnings
