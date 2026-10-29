self.addEventListener("install", (e) => {
  self.skipWaiting();
});
self.addEventListener("fetch", (e) => {
  // Pass-through network requests for live API calls
});