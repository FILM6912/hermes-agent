# Frontend Refactoring Tasks

## Phase 1: Setup Structure

- [x] 1. Create feature directory structure
  - [x] 1.1 Create `src/features/auth/` with subdirectories (components, types)
  - [x] 1.2 Create `src/features/chat/` with subdirectories (api, components, hooks, types)
  - [x] 1.3 Create `src/features/settings/` with subdirectories (components, components/tabs, types)
  - [x] 1.4 Create `src/features/sidebar/` with subdirectories (components, types)
  - [x] 1.5 Create `src/features/preview/` with subdirectories (components, types)
  - [x] 1.6 Create `src/app/` directory
  - [x] 1.7 Create `src/components/ui/` and `src/components/layouts/` directories

- [x] 2. Configure path aliases
  - [x] 2.1 Update `tsconfig.json` with @/ path alias configuration
  - [x] 2.2 Update `vite.config.ts` with @/ path alias configuration
  - [x] 2.3 Verify TypeScript recognizes the aliases

## Phase 2: Move Global Hooks and Providers

- [x] 3. Setup app providers
  - [x] 3.1 Create `src/app/providers.tsx` with ThemeProvider and LanguageProvider
  - [x] 3.2 Update `src/index.tsx` or `src/App.tsx` to use new providers structure

- [x] 4. Verify global hooks location
  - [x] 4.1 Ensure `src/hooks/useLanguage.tsx` is in correct location (no changes to content)
  - [x] 4.2 Ensure `src/hooks/useTheme.tsx` is in correct location
  - [x] 4.3 Ensure `src/hooks/useElectron.ts` is in correct location

## Phase 3: Migrate Auth Feature

- [x] 5. Move Auth components
  - [x] 5.1 Move `src/components/AuthPage.tsx` to `src/features/auth/components/AuthPage.tsx`
  - [x] 5.2 Update imports in `AuthPage.tsx` to use @/ aliases
  - [x] 5.3 Create `src/features/auth/types/index.ts` for auth-specific types
  - [x] 5.4 Create `src/features/auth/index.ts` with exports
  - [x] 5.5 Update `src/App.tsx` to import from `@/features/auth`

## Phase 4: Migrate Chat Feature

- [x] 6. Move Chat API
  - [x] 6.1 Move `src/services/geminiService.ts` to `src/features/chat/api/geminiService.ts`
  - [x] 6.2 Update imports in `geminiService.ts` to use @/ aliases

- [x] 7. Move Chat components
  - [x] 7.1 Extract `CodeBlock` component from `ChatInterface.tsx` to separate file `src/features/chat/components/CodeBlock.tsx`
  - [x] 7.2 Move `src/components/ChatInterface.tsx` to `src/features/chat/components/ChatInterface.tsx`
  - [x] 7.3 Update imports in `ChatInterface.tsx` to use @/ aliases
  - [x] 7.4 Update `ChatInterface.tsx` to import `CodeBlock` from same feature

- [x] 8. Setup Chat types and exports
  - [x] 8.1 Create `src/features/chat/types/index.ts` with Message, Attachment, MessageVersion types
  - [x] 8.2 Create `src/features/chat/index.ts` with exports
  - [x] 8.3 Update `src/App.tsx` to import from `@/features/chat`

## Phase 5: Migrate Settings Feature

- [x] 9. Extract Settings tabs
  - [x] 9.1 Extract GeneralTab from `SettingsView.tsx` to `src/features/settings/components/tabs/GeneralTab.tsx`
  - [x] 9.2 Extract AccountTab from `SettingsView.tsx` to `src/features/settings/components/tabs/AccountTab.tsx`
  - [x] 9.3 Extract ToolsTab from `SettingsView.tsx` to `src/features/settings/components/tabs/ToolsTab.tsx`
  - [x] 9.4 Extract AgentTab from `SettingsView.tsx` to `src/features/settings/components/tabs/AgentTab.tsx`
  - [x] 9.5 Extract LangflowTab from `SettingsView.tsx` to `src/features/settings/components/tabs/LangflowTab.tsx`

- [x] 10. Move Settings main component
  - [x] 10.1 Move `src/components/SettingsView.tsx` to `src/features/settings/components/SettingsView.tsx`
  - [x] 10.2 Update `SettingsView.tsx` to import tab components
  - [x] 10.3 Update imports in `SettingsView.tsx` to use @/ aliases

- [x] 11. Setup Settings types and exports
  - [x] 11.1 Create `src/features/settings/types/index.ts` with SettingsTab, AgentFlow types
  - [x] 11.2 Create `src/features/settings/index.ts` with exports
  - [x] 11.3 Update `src/App.tsx` to import from `@/features/settings`

## Phase 6: Migrate Sidebar Feature

- [x] 12. Move Sidebar component
  - [x] 12.1 Move `src/components/Sidebar.tsx` to `src/features/sidebar/components/Sidebar.tsx`
  - [x] 12.2 Update imports in `Sidebar.tsx` to use @/ aliases
  - [x] 12.3 Create `src/features/sidebar/types/index.ts` for sidebar-specific types
  - [x] 12.4 Create `src/features/sidebar/index.ts` with exports
  - [x] 12.5 Update `src/App.tsx` to import from `@/features/sidebar`

## Phase 7: Migrate Preview Feature

- [x] 13. Move Preview components
  - [x] 13.1 Move `src/components/PreviewWindow.tsx` to `src/features/preview/components/PreviewWindow.tsx`
  - [x] 13.2 Move `src/components/ProcessStep.tsx` to `src/features/preview/components/ProcessStep.tsx`
  - [x] 13.3 Update imports in both components to use @/ aliases
  - [x] 13.4 Create `src/features/preview/types/index.ts` with ProcessStep type
  - [x] 13.5 Create `src/features/preview/index.ts` with exports
  - [x] 13.6 Update `src/App.tsx` to import from `@/features/preview`

## Phase 8: Update Shared Components

- [x] 14. Keep shared components in src/components/
  - [x] 14.1 Update imports in `ErrorModal.tsx` to use @/ aliases
  - [x] 14.2 Update imports in `LangFlowConfigModal.tsx` to use @/ aliases
  - [x] 14.3 Update imports in `ElectronFileManager.tsx` to use @/ aliases

## Phase 9: Update Global Types

- [x] 15. Organize global types
  - [x] 15.1 Review `src/types/index.ts` and keep only truly global types
  - [x] 15.2 Move feature-specific types to respective feature/types/ folders
  - [x] 15.3 Update all imports to reference correct type locations

## Phase 10: Update Main App

- [x] 16. Update App.tsx imports
  - [x] 16.1 Update all feature imports to use @/features/\* pattern
  - [x] 16.2 Update all component imports to use @/ aliases
  - [x] 16.3 Update all hook imports to use @/ aliases
  - [x] 16.4 Update all type imports to use @/ aliases
  - [x] 16.5 Verify no relative imports remain (../)

## Phase 11: Apply Semantic Color Tokens

- [ ] 17. Update theme configuration
  - [ ] 17.1 Review and update `tailwind.config.js` with semantic color tokens
  - [ ] 17.2 Add CSS variables for theme colors if needed

- [ ] 18. Update component styling (if needed)
  - [ ] 18.1 Review components for hardcoded colors (bg-white, bg-black, etc.)
  - [ ] 18.2 Replace with semantic tokens (bg-background, text-foreground, etc.)
  - [ ] 18.3 Test dark/light mode switching

## Phase 12: Testing and Verification

- [x] 19. Run TypeScript compiler
  - [x] 19.1 Fix any TypeScript errors
  - [x] 19.2 Verify all imports resolve correctly
  - [x] 19.3 Ensure no type errors

- [ ] 20. Test all features manually
  - [ ] 20.1 Test authentication (login/signup)
  - [ ] 20.2 Test chat interface (send messages, attachments, code preview)
  - [ ] 20.3 Test settings (all tabs, save functionality)
  - [ ] 20.4 Test sidebar (navigation, chat history)
  - [ ] 20.5 Test preview window (HTML preview, process steps)
  - [ ] 20.6 Test language switching (EN/TH)
  - [ ] 20.7 Test theme switching (light/dark/system)

- [ ] 21. Verify translation system
  - [ ] 21.1 Confirm `useLanguage` hook works unchanged
  - [ ] 21.2 Confirm all `t()` calls work correctly
  - [ ] 21.3 Test language switching in all components

- [ ] 22. Check for console errors
  - [ ] 22.1 Open browser console and check for errors
  - [ ] 22.2 Fix any runtime errors
  - [ ] 22.3 Verify no 404 errors for imports

## Phase 13: Cleanup

- [x] 23. Remove old files and directories
  - [x] 23.1 Remove old `src/components/` files that were moved (keep only shared components)
  - [x] 23.2 Remove old `src/services/` directory if empty
  - [x] 23.3 Remove any empty directories

- [x] 24. Final verification
  - [x] 24.1 Run `npm run build` to ensure production build works
  - [x] 24.2 Test production build locally
  - [x] 24.3 Verify all features work in production build

## Phase 14: Documentation

- [x] 25. Update documentation
  - [x] 25.1 Update README.md with new project structure
  - [x] 25.2 Document feature organization pattern
  - [x] 25.3 Document import conventions

## Notes

- Each phase should be completed and tested before moving to the next
- Keep commits small and focused on specific tasks
- Test frequently to catch issues early
- If issues arise, fix them before proceeding
- Maintain backward compatibility throughout the process
