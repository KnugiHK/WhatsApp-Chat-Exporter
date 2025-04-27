const fs = require('fs-extra');
const marked = require('marked');
const path = require('path');
const markedAlert = require('marked-alert');

fs.ensureDirSync('docs');
fs.ensureDirSync('docs/imgs');

if (fs.existsSync('imgs')) {
  fs.copySync('imgs', 'docs/imgs');
}
if (fs.existsSync('.github/docs.html')) {
  fs.copySync('.github/docs.html', 'docs/docs.html');
}

const readmeContent = fs.readFileSync('README.md', 'utf8');

const toc = `<div class="table-of-contents">
                <h3>Table of Contents</h3>
                <ul>
                    <li><a href="#intro">Introduction</a></li>
                    <li><a href="#usage">Usage</a></li>
                    <li><a href="#todo">To Do</a></li>
                    <li><a href="#legal">Legal Stuff & Disclaimer</a></li>
                </ul>
            </div>
`

const generateHTML = (content) => 
`<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WhatsApp Chat Exporter</title>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <style>
        :root {
            --primary-color: #128C7E;
            --secondary-color: #25D366;
            --dark-color: #075E54;
            --light-color: #DCF8C6;
            --text-color: #333;
            --light-text: #777;
            --code-bg: #f6f8fa;
            --border-color: #e1e4e8;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: var(--text-color);
            background-color: #f9f9f9;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 0 20px;
        }
        
        header {
            background-color: var(--primary-color);
            color: white;
            padding: 60px 0 40px;
            text-align: center;
            box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        }
        
        header h1 {
            font-size: 2.8rem;
            margin-bottom: 16px;
        }
        
        .badges {
            margin: 20px 0;
            display: flex;
            justify-content: center;
            flex-wrap: wrap;
            gap: 10px;
        }
        
        .badge {
            display: inline-block;
            margin: 5px;
        }
        
        .tagline {
            font-size: 1.2rem;
            max-width: 800px;
            margin: 0 auto;
            padding: 0 20px;
        }
        
        .main-content {
            background: white;
            padding: 40px 0;
            margin: 0;
        }
        
        .inner-content {
            padding: 0 30px;
            max-width: 900px;
            margin: 0 auto;
        }
        
        h2 {
            color: var(--dark-color);
            margin: 30px 0 15px;
            padding-bottom: 8px;
            border-bottom: 2px solid var(--light-color);
            font-size: 1.8rem;
        }
        
        h3 {
            color: var(--dark-color);
            margin: 25px 0 15px;
            font-size: 1.4rem;
        }
        
        h4 {
            color: var(--dark-color);
            margin: 20px 0 10px;
            font-size: 1.2rem;
        }
        
        p, ul, ol {
            margin-bottom: 16px;
        }
        
        ul, ol {
            padding-left: 25px;
        }
        
        a {
            color: var(--primary-color);
            text-decoration: none;
        }
        
        a:hover {
            text-decoration: underline;
        }
        
        .alert {
            background-color: #f8f9fa;
            border-left: 4px solid #f0ad4e;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 3px;
        }
        
        .alert--tip {
            border-color: var(--secondary-color);
            background-color: rgba(37, 211, 102, 0.1);
        }
        
        .alert--note {
            border-color: #0088cc;
            background-color: rgba(0, 136, 204, 0.1);
        }
		 .markdown-alert {
            background-color: #f8f9fa;
            border-left: 4px solid #f0ad4e;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 3px;
        }
        
        .markdown-alert-note {
            border-color: #0088cc;
            background-color: rgba(0, 136, 204, 0.1);
        }
        
        .markdown-alert-tip {
            border-color: var(--secondary-color);
            background-color: rgba(37, 211, 102, 0.1);
        }
        
        .markdown-alert-important {
            border-color: #d9534f;
            background-color: rgba(217, 83, 79, 0.1);
        }
        
        .markdown-alert-warning {
            border-color: #f0ad4e;
            background-color: rgba(240, 173, 78, 0.1);
        }
        
        .markdown-alert-caution {
            border-color: #ff9800;
            background-color: rgba(255, 152, 0, 0.1);
        }
        
        .markdown-alert p {
            margin: 0;
        }
        
        .markdown-alert-title {
            font-weight: 600;
            margin-bottom: 8px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        pre {
            background-color: var(--code-bg);
            border-radius: 6px;
            padding: 16px;
            overflow-x: auto;
            margin: 16px 0;
            border: 1px solid var(--border-color);
        }
        
        code {
            font-family: SFMono-Regular, Consolas, Liberation Mono, Menlo, monospace;
            font-size: 85%;
            background-color: var(--code-bg);
            padding: 0.2em 0.4em;
            border-radius: 3px;
        }
        
        pre code {
            padding: 0;
            background-color: transparent;
        }
        
        .screenshot {
            max-width: 100%;
            border-radius: 8px;
            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
            margin: 20px 0;
            border: 1px solid var(--border-color);
        }
        
        .feature-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
            gap: 20px;
            margin: 30px 0;
        }
        
        .feature-card {
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
            padding: 20px;
            border: 1px solid var(--border-color);
            transition: transform 0.3s ease;
        }
        
        .feature-card:hover {
            transform: translateY(-5px);
            box-shadow: 0 5px 15px rgba(0, 0, 0, 0.1);
        }
        
        .feature-icon {
            font-size: 2rem;
            color: var(--primary-color);
            margin-bottom: 15px;
        }
        
        .feature-title {
            font-weight: 600;
            margin-bottom: 10px;
        }
        
        footer {
            background-color: var(--dark-color);
            color: white;
            text-align: center;
            padding: 30px 0;
            margin-top: 50px;
        }
        
        .btn {
            display: inline-block;
            background-color: var(--primary-color);
            color: white;
            padding: 10px 20px;
            border-radius: 4px;
            text-decoration: none;
            font-weight: 500;
            transition: background-color 0.3s ease;
            margin: 5px;
        }
        
        .btn:hover {
            background-color: var(--dark-color);
            text-decoration: none;
        }
        
        .btn-secondary {
            background-color: white;
            color: var(--primary-color);
            border: 1px solid var(--primary-color);
        }
        
        .btn-secondary:hover {
            background-color: var(--light-color);
            color: var(--dark-color);
        }
        
        .action-buttons {
            margin: 30px 0;
            text-align: center;
        }
        
        .table-of-contents {
            background-color: #f8f9fa;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            padding: 15px 25px;
            margin: 30px 0;
        }
        
        .table-of-contents h3 {
            margin-top: 0;
            margin-bottom: 10px;
        }
        
        .table-of-contents ul {
            margin-bottom: 0;
        }
        
        .help-text {
            color: var(--light-text);
            font-size: 0.9rem;
        }
        
        .device-section {
            padding: 15px;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            margin-bottom: 20px;
            background-color: #fff;
        }
        
        @media (max-width: 768px) {
            header {
                padding: 40px 0 30px;
            }
            
            header h1 {
                font-size: 2.2rem;
            }
            
            .tagline {
                font-size: 1.1rem;
            }
            
            .feature-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <header>
        <div class="container">
            <h1>WhatsApp Chat Exporter</h1>
            <div class="badges">
                <a href="https://pypi.org/project/whatsapp-chat-exporter/" class="badge"><img src="https://img.shields.io/pypi/v/whatsapp-chat-exporter?label=Latest%20in%20PyPI" alt="Latest in PyPI"></a>
                <a href="https://github.com/KnugiHK/WhatsApp-Chat-Exporter/blob/main/LICENSE" class="badge"><img src="https://img.shields.io/pypi/l/whatsapp-chat-exporter?color=427B93" alt="License MIT"></a>
                <a href="https://pypi.org/project/Whatsapp-Chat-Exporter/" class="badge"><img src="https://img.shields.io/pypi/pyversions/Whatsapp-Chat-Exporter" alt="Python"></a>
                <a href="https://matrix.to/#/#wtsexporter:matrix.org" class="badge"><img src="https://img.shields.io/matrix/wtsexporter:matrix.org.svg?label=Matrix%20Chat%20Room" alt="Matrix Chat Room"></a>
            </div>
            <p class="tagline">A customizable Android and iPhone Whatsapp database parser that will give you the history of your Whatsapp conversations in HTML and JSON</p>
            <div class="action-buttons">
                <a href="https://github.com/KnugiHK/WhatsApp-Chat-Exporter" class="btn"><i class="fab fa-github"></i> GitHub</a>
                <a href="https://pypi.org/project/whatsapp-chat-exporter/" class="btn btn-secondary"><i class="fab fa-python"></i> PyPI</a>
            </div>
        </div>
    </header>
    
    <div class="main-content">
        <div class="inner-content">
            <section id="features">
                <h2>Key Features</h2>
                
                <div class="feature-grid">
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-mobile-alt"></i></div>
                        <h3 class="feature-title">Cross-Platform</h3>
                        <p>Support for both Android and iOS/iPadOS WhatsApp databases</p>
                    </div>
                    
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-lock"></i></div>
                        <h3 class="feature-title">Backup Decryption</h3>
                        <p>Support for Crypt12, Crypt14, and Crypt15 (End-to-End) encrypted backups</p>
                    </div>
                    
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-file-export"></i></div>
                        <h3 class="feature-title">Multiple Formats</h3>
                        <p>Export your chats in HTML, JSON, and text formats</p>
                    </div>
                    
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-paint-brush"></i></div>
                        <h3 class="feature-title">Customizable</h3>
                        <p>Use custom HTML templates and styling for your chat exports</p>
                    </div>
                    
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-images"></i></div>
                        <h3 class="feature-title">Media Support</h3>
                        <p>Properly handles and organizes your media files in the exports</p>
                    </div>
                    
                    <div class="feature-card">
                        <div class="feature-icon"><i class="fas fa-filter"></i></div>
                        <h3 class="feature-title">Filtering Options</h3>
                        <p>Filter chats by date, phone number, and more</p>
                    </div>
                </div>
            </section>
			
            <div class="readme-content">
                ${content}
            </div>
            
            
            <div class="action-buttons">
                <a href="https://github.com/KnugiHK/WhatsApp-Chat-Exporter" class="btn"><i class="fab fa-github"></i> View on GitHub</a>
                <a href="https://pypi.org/project/whatsapp-chat-exporter/" class="btn btn-secondary"><i class="fab fa-python"></i> PyPI Package</a>
            </div>
        </div>
    </div>
    
    <footer>
        <div class="container">
            <p>© 2021-${new Date().getFullYear()} WhatsApp Chat Exporter</p>
            <p>Licensed under MIT License</p>
            <p>
                <a href="https://github.com/KnugiHK/WhatsApp-Chat-Exporter" style="color: white; margin: 0 10px;"><i class="fab fa-github fa-lg"></i></a>
                <a href="https://matrix.to/#/#wtsexporter:matrix.org" style="color: white; margin: 0 10px;"><i class="fas fa-comments fa-lg"></i></a>
            </p>
            <p><small>Last updated: ${new Date().toLocaleDateString()}</small></p>
        </div>
    </footer>
    
    <script>
        // Simple script to handle smooth scrolling for anchor links
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                e.preventDefault();
                
                const targetId = this.getAttribute('href');
                const targetElement = document.querySelector(targetId);
                
                if (targetElement) {
                    window.scrollTo({
                        top: targetElement.offsetTop - 20,
                        behavior: 'smooth'
                    });
                }
            });
        });
    </script>
</body>
</html>
`;

const processedContent = readmeContent.replace(/\[!\[.*?\]\(.*?\)\]\(.*?\)/g, '').replace(/!\[.*?\]\(.*?\)/g, '')

const htmlContent = marked.use(markedAlert()).parse(processedContent, {
  gfm: true,
  breaks: true,
  renderer: new marked.Renderer()
});

const finalHTML = generateHTML(htmlContent);
fs.writeFileSync('docs/index.html', finalHTML);

console.log('Website generated successfully!');