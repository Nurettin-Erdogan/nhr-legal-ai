import { cva } from "class-variance-authority";

export const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium cursor-pointer transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50 disabled:cursor-not-allowed [&_svg]:pointer-events-none [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground shadow-sm hover:bg-destructive/90",
        outline:
          "border border-input bg-background shadow-sm hover:bg-accent hover:text-accent-foreground",
        secondary: "bg-secondary text-secondary-foreground shadow-sm hover:bg-secondary/80",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
        hero: "bg-gradient-gold text-primary font-semibold shadow-gold transition-[transform,box-shadow] duration-300 hover:shadow-elegant hover:-translate-y-0.5",
        elite:
          "bg-primary text-primary-foreground shadow-elegant transition-[transform,background-color] duration-300 hover:bg-primary-glow hover:-translate-y-0.5",
        gold: "bg-gold text-primary font-medium transition-colors hover:bg-gold-deep hover:text-primary-foreground",
        "outline-gold":
          "border border-gold/60 bg-transparent text-foreground transition-colors hover:bg-gold/10 hover:border-gold",
        "outline-light":
          "border border-primary-foreground/40 bg-transparent text-primary-foreground transition-colors hover:bg-primary-foreground/10",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-9 rounded-md px-3",
        lg: "h-12 rounded-lg px-8 text-base",
        xl: "h-14 rounded-lg px-10 text-base",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);
