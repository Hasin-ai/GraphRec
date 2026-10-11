import { HOME_TITLE } from "../../marketing/copy";
import { useDocumentTitle } from "../../marketing/useDocumentTitle";
import { ConsolePreview } from "./sections/ConsolePreview";
import { Developers } from "./sections/Developers";
import { Features } from "./sections/Features";
import { FinalCta } from "./sections/FinalCta";
import { Hero } from "./sections/Hero";
import { HowItWorks } from "./sections/HowItWorks";
import { PricingTeaser } from "./sections/PricingTeaser";
import { Problem } from "./sections/Problem";
import { Security } from "./sections/Security";

/** `/` for signed-out visitors. One h1 (the hero), one h2 per section. */
export function LandingPage() {
  useDocumentTitle(HOME_TITLE);
  return <>
    <Hero />
    <Problem />
    <Features />
    <HowItWorks />
    <Developers />
    <Security />
    <ConsolePreview />
    <PricingTeaser />
    <FinalCta />
  </>;
}
