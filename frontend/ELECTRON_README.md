# AI Agent - Electron Desktop App

แอปพลิเคชัน AI Agent ที่รองรับทั้งเว็บและ Desktop App บน Windows

## 🚀 การติดตั้ง

### 1. ติดตั้ง Dependencies

```bash
npm install
```

## 💻 การพัฒนา (Development)

### รันเป็นเว็บแอป
```bash
npm run dev
```
เปิดเบราว์เซอร์ที่ http://localhost:5173

### รันเป็น Electron App
```bash
npm run electron:dev
```
จะเปิดหน้าต่าง Desktop App โดยอัตโนมัติ

## 📦 Build สำหรับ Production

### Build เว็บแอป
```bash
npm run build
```
ไฟล์จะอยู่ในโฟลเดอร์ `dist/`

### Build Windows Desktop App
```bash
npm run electron:build:win
```
ไฟล์ installer จะอยู่ในโฟลเดอร์ `dist-electron/`

### Build สำหรับทุกแพลตฟอร์ม
```bash
npm run electron:build
```

## 🔧 ฟีเจอร์ Electron

### File System Access
แอป Electron สามารถเข้าถึงไฟล์ในเครื่องได้:

```typescript
import { useElectron, electronFileSystem } from './hooks/useElectron';

// ใช้ใน Component
function MyComponent() {
  const { isElectron, api } = useElectron();
  
  const handleSelectFolder = async () => {
    const folderPath = await electronFileSystem.selectFolder();
    if (folderPath) {
      console.log('Selected folder:', folderPath);
    }
  };
  
  const handleReadFile = async () => {
    const filePath = await electronFileSystem.selectFile();
    if (filePath) {
      const content = await electronFileSystem.readFile(filePath);
      console.log('File content:', content);
    }
  };
  
  return (
    <div>
      {isElectron && (
        <>
          <button onClick={handleSelectFolder}>Select Folder</button>
          <button onClick={handleReadFile}>Read File</button>
        </>
      )}
    </div>
  );
}
```

### Available APIs

#### Dialog APIs
- `electronFileSystem.selectFolder()` - เลือกโฟลเดอร์
- `electronFileSystem.selectFile()` - เลือกไฟล์

#### File System APIs
- `electronFileSystem.readFile(path)` - อ่านไฟล์
- `electronFileSystem.writeFile(path, content)` - เขียนไฟล์
- `electronFileSystem.readDir(path)` - อ่านรายการไฟล์ในโฟลเดอร์
- `electronFileSystem.createDir(path)` - สร้างโฟลเดอร์
- `electronFileSystem.deleteFile(path)` - ลบไฟล์

## 📁 โครงสร้างโปรเจค

```
.
├── electron/
│   ├── main.js          # Electron main process
│   └── preload.js       # Preload script (IPC bridge)
├── hooks/
│   └── useElectron.ts   # React hook สำหรับ Electron API
├── electron.d.ts        # TypeScript types
├── src/                 # React app source
├── dist/                # Web build output
└── dist-electron/       # Electron build output
```

## 🔐 Security

- ใช้ `contextIsolation: true` เพื่อความปลอดภัย
- ใช้ `nodeIntegration: false` 
- Expose เฉพาะ API ที่จำเป็นผ่าน preload script

## 🌐 Web vs Desktop

แอปจะตรวจสอบอัตโนมัติว่ากำลังรันบนเว็บหรือ Desktop:

```typescript
const { isElectron } = useElectron();

if (isElectron) {
  // แสดงฟีเจอร์เฉพาะ Desktop
} else {
  // แสดงฟีเจอร์เว็บ
}
```

## 📝 หมายเหตุ

- Port สำหรับ dev: `5173` (Vite default)
- Electron จะโหลดจาก `http://localhost:5173` ในโหมด development
- ในโหมด production จะโหลดจาก `dist/index.html`

## 🐛 Troubleshooting

### ปัญหา: Electron ไม่เปิด
- ตรวจสอบว่า Vite dev server รันอยู่ที่ port 5173
- ลองรัน `npm run dev` ก่อน แล้วค่อยรัน `npm run electron:dev` ในอีก terminal

### ปัญหา: Build ไม่สำเร็จ
- ตรวจสอบว่ามี icon.ico ในโฟลเดอร์ `public/`
- ลองลบ `node_modules` และ `package-lock.json` แล้ว install ใหม่

### ปัญหา: File System API ไม่ทำงาน
- ตรวจสอบว่ารันใน Electron (ไม่ใช่เว็บเบราว์เซอร์)
- ตรวจสอบ console สำหรับ error messages
