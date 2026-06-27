# 🚀 Quick Start - Electron Desktop App

## การติดตั้งและรัน

### 1. ติดตั้ง Dependencies
```bash
npm install
```

### 2. รันแอป

#### รันเป็นเว็บ (Web Browser)
```bash
npm run dev
```
เปิด: http://localhost:5173

#### รันเป็น Desktop App (Electron)
```bash
npm run electron:dev
```

### 3. Build สำหรับ Production

#### Build Windows Installer
```bash
npm run electron:build:win
```
ไฟล์ `.exe` จะอยู่ใน `dist-electron/`

## 📝 การใช้งาน File System API

### ตัวอย่างการเพิ่มปุ่มเลือกไฟล์ใน Component

```tsx
import { useElectron, electronFileSystem } from './hooks/useElectron';

function MyComponent() {
  const { isElectron } = useElectron();

  const handleOpenFile = async () => {
    const filePath = await electronFileSystem.selectFile();
    if (filePath) {
      const content = await electronFileSystem.readFile(filePath);
      console.log('File content:', content);
    }
  };

  return (
    <div>
      {isElectron && (
        <button onClick={handleOpenFile}>
          Open File
        </button>
      )}
    </div>
  );
}
```

## 🎯 ฟีเจอร์หลัก

✅ รันได้ทั้งเว็บและ Desktop App  
✅ เข้าถึงไฟล์ในเครื่องได้ (เฉพาะ Desktop)  
✅ อ่าน/เขียนไฟล์  
✅ เลือกโฟลเดอร์และไฟล์  
✅ จัดการไฟล์และโฟลเดอร์  

## 📦 ไฟล์สำคัญ

- `electron/main.js` - Electron main process
- `electron/preload.js` - IPC bridge
- `hooks/useElectron.ts` - React hook สำหรับ Electron API
- `electron.d.ts` - TypeScript types

## 🔧 API ที่ใช้ได้

```typescript
// เลือกโฟลเดอร์
const folder = await electronFileSystem.selectFolder();

// เลือกไฟล์
const file = await electronFileSystem.selectFile();

// อ่านไฟล์
const content = await electronFileSystem.readFile(path);

// เขียนไฟล์
await electronFileSystem.writeFile(path, content);

// อ่านรายการไฟล์ในโฟลเดอร์
const files = await electronFileSystem.readDir(path);

// สร้างโฟลเดอร์
await electronFileSystem.createDir(path);

// ลบไฟล์
await electronFileSystem.deleteFile(path);
```

## 💡 Tips

1. ใช้ `isElectron` เพื่อแสดงฟีเจอร์เฉพาะ Desktop
2. ทดสอบทั้งบนเว็บและ Desktop
3. File System API จะใช้ได้เฉพาะใน Electron เท่านั้น

## 🐛 หากมีปัญหา

ดูรายละเอียดเพิ่มเติมใน `ELECTRON_README.md`
