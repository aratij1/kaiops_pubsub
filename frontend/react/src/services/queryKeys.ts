export const alertQueryKeys = {
  all: ["alerts"] as const,
  lists: () => [...alertQueryKeys.all, "list"] as const,
  list: (limit: number) => [...alertQueryKeys.lists(), { limit }] as const,
  landingPad: (limit: number) => [...alertQueryKeys.all, "landing-pad", { limit, includeArchive: false }] as const,
};
