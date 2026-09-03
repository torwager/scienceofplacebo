/* Site configuration. Giscus values come from https://giscus.app after enabling GitHub Discussions
   and installing the giscus app on torwager/scienceofplacebo. */
window.SOP_CONFIG = {
  repo: "torwager/scienceofplacebo",
  giscus: {
    repoId: "R_kgDOUMJV2A",
    category: "General",
    categoryId: "DIC_kwDOUMJV2M4DEvFY",   // TODO: create a "Papers" category in GitHub Discussions and put its id here
    generalCategory: "General",
    generalCategoryId: "DIC_kwDOUMJV2M4DEvFY"
  },
  // Community API (Cloudflare Worker, see worker/README.md). Empty until deployed; then e.g. "https://community.scienceofplacebo.org".
  communityApi: "",
  // Private full-text store (authenticated). Empty until the store is configured.
  privatePdfBase: ""
};
