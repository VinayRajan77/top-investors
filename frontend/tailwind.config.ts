import type { Config } from 'tailwindcss';
export default { content:['./app/**/*.{js,ts,jsx,tsx}'], theme:{extend:{colors:{ink:'#17251f',moss:'#26715b',mist:'#f3f5ef',paper:'#fffefa'},boxShadow:{card:'0 12px 30px rgba(22, 40, 32, .08)'}}}, plugins:[] } satisfies Config;
