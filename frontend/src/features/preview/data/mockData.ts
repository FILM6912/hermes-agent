import { FileNode } from "../components/FileTreeItem";

export const INITIAL_FILE_SYSTEM: FileNode[] = [
  {
    name: "src",
    type: "folder",
    isOpen: true,
    children: [
      {
        name: "components",
        type: "folder",
        isOpen: true,
        children: [
          {
            name: "Hero.tsx",
            type: "file",
            content: `import React from 'react';\n\nexport const Hero = () => {\n  return (\n    <section className="pt-32 pb-20 px-6">\n      <h1 className="text-6xl font-bold bg-gradient-to-r from-blue-400 to-purple-600 bg-clip-text text-transparent">\n        Build faster.\n      </h1>\n      <p className="mt-6 text-xl text-gray-400">Deploy AI agents in seconds.</p>\n    </section>\n  );\n};`,
          },
          {
            name: "Navbar.tsx",
            type: "file",
            content: `import React from 'react';\n\nexport const Navbar = () => (\n  <nav className="fixed w-full z-50 bg-black/50 backdrop-blur border-b border-white/10 p-4 flex justify-between items-center">\n    <div className="font-bold text-xl">Acme Inc</div>\n    <div className="flex gap-4">\n      <a href="#features">Features</a>\n      <a href="#pricing">Pricing</a>\n    </div>\n  </nav>\n);`,
          },
        ],
      },
      {
        name: "App.tsx",
        type: "file",
        content: `import { Navbar } from './components/Navbar';\nimport { Hero } from './components/Hero';\n\nfunction App() {\n  return (\n    <div className="min-h-screen bg-black text-white">\n      <Navbar />\n      <Hero />\n    </div>\n  );\n}\n\nexport default App;`,
      },
    ],
  },
  {
    name: "README.md",
    type: "file",
    content: `# Modern Landing Page\n\nA high-conversion landing page built with React and Tailwind CSS.\n\n## Stack\n- React 19\n- Tailwind CSS`,
  },
];

export const MOCK_DASHBOARD_HTML = `<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Landing Page Preview</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body { background-color: #09090b; color: #fafafa; }
        .hero-gradient {
            background: radial-gradient(circle at top center, #1e1b4b 0%, #09090b 60%);
        }
    </style>
</head>
<body class="font-sans antialiased">
    <nav class="fixed w-full z-50 bg-background/80 backdrop-blur-md border-b border-white/10">
        <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
            <div class="font-bold text-xl">Acme AI</div>
        </div>
    </nav>
    <section class="hero-gradient pt-32 pb-20 px-6">
        <div class="max-w-7xl mx-auto text-center">
            <h1 class="text-5xl md:text-7xl font-bold">
                Build software faster with intelligent agents.
            </h1>
        </div>
    </section>
</body>
</html>`;
