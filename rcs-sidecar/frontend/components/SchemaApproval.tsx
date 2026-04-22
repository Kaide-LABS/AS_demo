export default function SchemaApproval() {
  return (
    <div className="flex bg-gray-900 text-white p-4 h-full gap-4">
      <div className="w-1/3 border-r border-gray-700 p-2">
        <h3 className="font-bold">Sections</h3>
        <div className="text-green-400">Segments (Approved)</div>
        <div className="text-yellow-400">Demographics (Pending)</div>
      </div>
      <div className="w-2/3 p-2">
        <h3 className="font-bold">Field Details</h3>
        <div className="bg-gray-800 p-2 rounded mt-2">
          <p>age_range: 25-44</p>
          <div className="space-x-2 mt-2">
            <button className="bg-green-600 px-2 py-1 rounded">Approve</button>
            <button className="bg-red-600 px-2 py-1 rounded">Reject</button>
          </div>
        </div>
      </div>
    </div>
  )
}
