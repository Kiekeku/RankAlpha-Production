import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: ["class"],
  content: [
    './src/pages/**/*.{js,ts,jsx,tsx,mdx}',
    './src/components/**/*.{js,ts,jsx,tsx,mdx}',
    './src/app/**/*.{js,ts,jsx,tsx,mdx}',
    './src/features/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    container: {
      center: true,
      padding: "2rem",
      screens: {
        sm: "100%",
        md: "100%",
        lg: "100%",
        xl: "100%",
        "2xl": "100%",
      },
    },
    extend: {
      colors: {
        border: "hsl(var(--border))",
        outline: "hsl(var(--outline))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))",
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))",
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))",
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))",
        },
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))",
        },
        gain: {
          DEFAULT: "hsl(var(--gain))",
          soft: "hsl(var(--gain-soft))",
        },
        loss: {
          DEFAULT: "hsl(var(--loss))",
          soft: "hsl(var(--loss-soft))",
        },
        neutralsoft: "hsl(var(--neutral-soft))",
        status: {
          success: {
            DEFAULT: "hsl(var(--status-success))",
            foreground: "hsl(var(--status-success-foreground))",
            soft: "hsl(var(--status-success-soft))",
          },
          danger: {
            DEFAULT: "hsl(var(--status-danger))",
            foreground: "hsl(var(--status-danger-foreground))",
            soft: "hsl(var(--status-danger-soft))",
          },
          warning: {
            DEFAULT: "hsl(var(--status-warning))",
            foreground: "hsl(var(--status-warning-foreground))",
            soft: "hsl(var(--status-warning-soft))",
          },
          info: {
            DEFAULT: "hsl(var(--status-info))",
            foreground: "hsl(var(--status-info-foreground))",
            soft: "hsl(var(--status-info-soft))",
          },
          model: {
            DEFAULT: "hsl(var(--status-model))",
            foreground: "hsl(var(--status-model-foreground))",
            soft: "hsl(var(--status-model-soft))",
          },
        },
      },
      spacing: {
        "ds-1": "0.25rem", // 4px
        "ds-2": "0.5rem", // 8px
        "ds-3": "0.75rem", // 12px
        "ds-4": "1rem", // 16px
        "ds-5": "1.25rem", // 20px
        "ds-6": "1.5rem", // 24px
        "ds-7": "2rem", // 32px
        "ds-8": "2.5rem", // 40px
        "ds-9": "3rem", // 48px
        "ds-10": "4rem", // 64px
      },
      fontSize: {
        "ds-xs": ["0.75rem", { lineHeight: "1rem" }], // 12px
        "ds-sm": ["0.875rem", { lineHeight: "1.25rem" }], // 14px
        "ds-md": ["1rem", { lineHeight: "1.5rem" }], // 16px
        "ds-lg": ["1.25rem", { lineHeight: "1.75rem" }], // 20px
        "ds-xl": ["1.75rem", { lineHeight: "2.25rem" }], // 28px
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}
export default config
