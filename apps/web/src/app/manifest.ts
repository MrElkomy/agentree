import type { MetadataRoute } from "next";

// Lets the dashboard be added to the home screen (required for Web Push on iPhone and iPad).
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "Agentree",
    short_name: "Agentree",
    description: "Your AI Team. Always On.",
    start_url: "/dashboard",
    display: "standalone",
    background_color: "#F7F9FC",
    theme_color: "#101B2B",
    icons: [{ src: "/apple-icon.png", sizes: "180x180", type: "image/png" }],
  };
}
